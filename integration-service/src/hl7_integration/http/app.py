import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError

from hl7_integration.config import Settings
from hl7_integration.database.connection_pool import open_connection_pool
from hl7_integration.database.inbound_message_repository import (
    find_message_by_id,
    list_messages,
)
from hl7_integration.database.message_event_repository import list_message_events
from hl7_integration.forwarding.dead_letter_service import replay_dead_lettered_message
from hl7_integration.forwarding.forwarding_worker import ForwardingWorker, build_forwarding_worker
from hl7_integration.forwarding.hmac_signer import (
    CLIENT_ID_HEADER,
    SIGNATURE_HEADER,
    is_valid_signature,
)
from hl7_integration.forwarding.lab_result_api_client import CORRELATION_ID_HEADER
from hl7_integration.models.batch_request import BatchRequest
from hl7_integration.models.message_status import MessageStatus
from hl7_integration.processing.batch_processor import BatchItem, BatchProcessor
from hl7_integration.processing.message_processor import MessageProcessor

HL7_MEDIA_TYPE = "application/hl7-v2"

logger = logging.getLogger(__name__)


def create_app(settings: Settings, run_forwarding_worker: bool = True) -> FastAPI:
    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        connection_pool = await open_connection_pool(settings)
        app.state.connection_pool = connection_pool
        app.state.message_processor = MessageProcessor(
            connection_pool=connection_pool,
            max_delivery_attempts=settings.delivery_max_attempts,
            local_application=settings.local_application,
            local_facility=settings.local_facility,
        )
        app.state.batch_processor = BatchProcessor(connection_pool)
        stop_event = asyncio.Event()
        forwarding_worker: ForwardingWorker | None = None
        worker_task: asyncio.Task[None] | None = None
        if run_forwarding_worker:
            forwarding_worker = build_forwarding_worker(settings, connection_pool)
            worker_task = asyncio.create_task(forwarding_worker.run_until_stopped(stop_event))
        try:
            yield
        finally:
            stop_event.set()
            if worker_task is not None:
                await worker_task
            if forwarding_worker is not None:
                await forwarding_worker.close()
            await connection_pool.close()

    app = FastAPI(title="HL7 Integration Service", lifespan=lifespan)

    @app.post("/hl7/messages")
    async def receive_hl7_message(
        request: Request,
        correlation_id_header: Annotated[str | None, Header(alias=CORRELATION_ID_HEADER)] = None,
    ) -> Response:
        raw_message = (await request.body()).decode("utf-8", errors="replace")
        processing_result = await request.app.state.message_processor.process_message(
            raw_message,
            correlation_id=_parse_uuid_or_none(correlation_id_header),
        )
        return Response(
            content=processing_result.acknowledgment_message,
            media_type=HL7_MEDIA_TYPE,
            headers={CORRELATION_ID_HEADER: str(processing_result.correlation_id)},
        )

    @app.post("/batches")
    async def look_up_batch(
        request: Request,
        correlation_id_header: Annotated[str | None, Header(alias=CORRELATION_ID_HEADER)] = None,
    ) -> JSONResponse:
        request_body = await request.body()
        if not _is_signed(request, request_body):
            return JSONResponse({"detail": "Invalid service credentials."}, 401)
        try:
            batch_request = BatchRequest.model_validate_json(request_body)
        except ValidationError as validation_error:
            return JSONResponse({"detail": validation_error.errors(include_url=False)}, 422)
        if len(batch_request.items) > settings.batch_max_records:
            return JSONResponse(
                {"detail": f"A batch may contain at most {settings.batch_max_records} items."}, 422
            )
        if len({item.item_id for item in batch_request.items}) != len(batch_request.items):
            return JSONResponse({"detail": "item_id values must be unique."}, 422)

        correlation_id = _parse_uuid_or_none(correlation_id_header) or uuid4()
        item_results = await request.app.state.batch_processor.process_batch(
            batch_request.batch_id,
            [BatchItem(item.item_id, item.message_id) for item in batch_request.items],
        )
        return JSONResponse(
            {
                "batch_id": batch_request.batch_id,
                "results": [
                    {
                        "item_id": item_result.item_id,
                        "message_id": item_result.message_id,
                        "status": item_result.status.value,
                        "retryable": item_result.retryable,
                        "correlation_id": (
                            str(item_result.correlation_id) if item_result.correlation_id else None
                        ),
                        "payload": item_result.payload,
                        "error": item_result.error,
                    }
                    for item_result in item_results
                ],
            },
            headers={CORRELATION_ID_HEADER: str(correlation_id)},
        )

    def _is_signed(request: Request, request_body: bytes) -> bool:
        shared_secret = settings.hl7_api_hmac_secret.get_secret_value()
        if not shared_secret or request.headers.get(CLIENT_ID_HEADER) != settings.hl7_int_client_id:
            return False
        request_uri = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return is_valid_signature(
            shared_secret,
            request.method,
            request_uri,
            request_body,
            request.headers.get(SIGNATURE_HEADER, ""),
        )

    @app.get("/health")
    async def health_check(request: Request) -> JSONResponse:
        try:
            async with request.app.state.connection_pool.connection() as connection:
                await connection.execute("SELECT 1")
        except Exception:
            logger.exception("Health check failed")
            return JSONResponse({"status": "unhealthy", "database": "unavailable"}, 503)
        return JSONResponse({"status": "ok", "database": "ok"})

    @app.get("/messages")
    async def search_messages(
        request: Request,
        status: MessageStatus | None = None,
        message_control_id: str | None = None,
        order_no: str | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 50,
    ) -> list[dict[str, Any]]:
        async with request.app.state.connection_pool.connection() as connection:
            return await list_messages(connection, status, message_control_id, order_no, limit)

    @app.get("/messages/{inbound_message_id}")
    async def get_message_trace(request: Request, inbound_message_id: UUID) -> dict[str, Any]:
        async with request.app.state.connection_pool.connection() as connection:
            message = await find_message_by_id(connection, inbound_message_id)
            if message is None:
                raise HTTPException(status_code=404, detail="Message not found")
            events = await list_message_events(connection, inbound_message_id)
        return {"message": message, "events": events}

    @app.post("/messages/{inbound_message_id}/replay")
    async def replay_message(request: Request, inbound_message_id: UUID) -> dict[str, Any]:
        was_replayed = await replay_dead_lettered_message(
            request.app.state.connection_pool,
            inbound_message_id,
            settings.delivery_max_attempts,
            requested_by="http-admin",
        )
        if not was_replayed:
            raise HTTPException(status_code=409, detail="Message is not dead-lettered")
        return {"inbound_message_id": str(inbound_message_id), "status": "pending"}

    return app


def _parse_uuid_or_none(value: str | None) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(value)
    except ValueError:
        return None
