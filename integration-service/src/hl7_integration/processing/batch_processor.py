import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from hl7_integration.database.inbound_message_repository import (
    find_accepted_messages_by_control_ids,
)
from hl7_integration.database.message_event_repository import record_message_event
from hl7_integration.mapping.remap import RemapError, remap_stored_message
from hl7_integration.models.message_status import MessageEventType

logger = logging.getLogger(__name__)


class BatchItemStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    ERROR = "error"


@dataclass(frozen=True)
class BatchItem:
    item_id: int
    message_id: str


@dataclass(frozen=True)
class BatchItemResult:
    item_id: int
    message_id: str
    status: BatchItemStatus
    retryable: bool = False
    correlation_id: UUID | None = None
    payload: dict[str, Any] | None = None
    error: str | None = None


class BatchProcessor:
    def __init__(self, connection_pool: AsyncConnectionPool) -> None:
        self.connection_pool = connection_pool

    async def process_batch(self, batch_id: str, items: list[BatchItem]) -> list[BatchItemResult]:
        async with self.connection_pool.connection() as connection:
            messages_by_control_id = await find_accepted_messages_by_control_ids(
                connection, sorted({item.message_id for item in items})
            )

        item_results = [
            self._resolve_item(item, messages_by_control_id.get(item.message_id, []))
            for item in items
        ]
        await self._record_fetch_events(batch_id, item_results, messages_by_control_id)
        logger.info(
            "Batch %s looked up: %d items, %d found",
            batch_id,
            len(item_results),
            sum(result.status is BatchItemStatus.FOUND for result in item_results),
        )
        return item_results

    def _resolve_item(self, item: BatchItem, matches: list[dict[str, Any]]) -> BatchItemResult:
        if not matches:
            return BatchItemResult(item.item_id, item.message_id, BatchItemStatus.NOT_FOUND)
        if len(matches) > 1:
            return BatchItemResult(
                item.item_id,
                item.message_id,
                BatchItemStatus.AMBIGUOUS,
                error=f"{len(matches)} senders used message ID {item.message_id}",
            )
        stored_message = matches[0]
        try:
            payload = self._payload_for(stored_message)
        except Exception as lookup_error:
            logger.exception("Batch lookup failed for message_control_id=%s", item.message_id)
            return BatchItemResult(
                item.item_id,
                item.message_id,
                BatchItemStatus.ERROR,
                retryable=True,
                error=str(lookup_error),
            )
        return BatchItemResult(
            item.item_id,
            item.message_id,
            BatchItemStatus.FOUND,
            correlation_id=stored_message["correlation_id"],
            payload=payload,
        )

    @staticmethod
    def _payload_for(stored_message: dict[str, Any]) -> dict[str, Any]:
        try:
            return remap_stored_message(stored_message["raw_payload"])
        except RemapError:
            if stored_message["normalized_payload"] is None:
                raise
            logger.warning(
                "Re-mapping failed for inbound_message_id=%s; using stored payload",
                stored_message["id"],
            )
            return stored_message["normalized_payload"]

    async def _record_fetch_events(
        self,
        batch_id: str,
        item_results: list[BatchItemResult],
        messages_by_control_id: dict[str, list[dict[str, Any]]],
    ) -> None:
        found_results = [r for r in item_results if r.status is BatchItemStatus.FOUND]
        if not found_results:
            return
        async with self.connection_pool.connection() as connection, connection.transaction():
            for item_result in found_results:
                stored_message = messages_by_control_id[item_result.message_id][0]
                await record_message_event(
                    connection,
                    stored_message["id"],
                    stored_message["correlation_id"],
                    MessageEventType.BATCH_FETCHED,
                    detail={"batch_id": batch_id, "item_id": item_result.item_id},
                )
