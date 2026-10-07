"""Background worker that forwards queued lab results to the API with retries."""

import asyncio
import contextlib
import logging
import socket
from typing import Any

from psycopg_pool import AsyncConnectionPool

from hl7_integration.config import Settings
from hl7_integration.database.inbound_message_repository import (
    ClaimedMessage,
    claim_due_messages,
    mark_message_dead_lettered,
    mark_message_delivered,
    schedule_message_retry,
)
from hl7_integration.database.message_event_repository import record_message_event
from hl7_integration.forwarding.lab_result_api_client import ForwardingOutcome, LabResultApiClient
from hl7_integration.forwarding.retry_policy import RetryPolicy
from hl7_integration.models.message_status import MessageEventType

logger = logging.getLogger(__name__)


class ForwardingWorker:
    def __init__(
        self,
        connection_pool: AsyncConnectionPool,
        api_client: LabResultApiClient,
        retry_policy: RetryPolicy,
        batch_size: int,
        lease_seconds: float,
        poll_interval_seconds: float,
        worker_name: str | None = None,
    ) -> None:
        self._connection_pool = connection_pool
        self._api_client = api_client
        self._retry_policy = retry_policy
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self.worker_name = worker_name or f"{socket.gethostname()}:{id(self):x}"

    async def close(self) -> None:
        await self._api_client.close()

    async def run_until_stopped(self, stop_event: asyncio.Event) -> None:
        logger.info("Forwarding worker %s started", self.worker_name)
        while not stop_event.is_set():
            try:
                processed_count = await self.process_due_messages()
            except Exception:
                logger.exception("Delivery cycle failed; will retry after the poll interval")
                processed_count = 0
            if processed_count == 0:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop_event.wait(), self._poll_interval_seconds)
        logger.info("Forwarding worker %s stopped", self.worker_name)

    async def process_due_messages(self) -> int:
        """Claim one batch of due messages, deliver them concurrently."""
        claimed_messages = await self._claim_batch()
        await asyncio.gather(*(self._deliver(message) for message in claimed_messages))
        return len(claimed_messages)

    async def _claim_batch(self) -> list[ClaimedMessage]:
        async with self._connection_pool.connection() as connection, connection.transaction():
            claimed_messages = await claim_due_messages(
                connection, self._batch_size, self._lease_seconds
            )
            for claimed_message in claimed_messages:
                await record_message_event(
                    connection,
                    claimed_message.inbound_message_id,
                    claimed_message.correlation_id,
                    MessageEventType.DELIVERY_ATTEMPTED,
                    attempt_number=claimed_message.attempt_count,
                    detail={"worker": self.worker_name},
                )
        return claimed_messages

    async def _deliver(self, claimed_message: ClaimedMessage) -> None:
        try:
            forwarding_outcome = await self._api_client.send_lab_result(
                claimed_message.normalized_payload, claimed_message.correlation_id
            )
        except Exception as unexpected_error:
            logger.exception(
                "Unexpected error while delivering message %s", claimed_message.inbound_message_id
            )
            forwarding_outcome = ForwardingOutcome(
                is_delivered=False,
                is_retryable=True,
                http_status=None,
                error_message=f"Unexpected delivery error: {unexpected_error!r}",
            )
        await self._record_outcome(claimed_message, forwarding_outcome)

    async def _record_outcome(
        self, claimed_message: ClaimedMessage, forwarding_outcome: ForwardingOutcome
    ) -> None:
        attempt_number = claimed_message.attempt_count
        outcome_detail: dict[str, Any] = {
            "worker": self.worker_name,
            "http_status": forwarding_outcome.http_status,
            "response_excerpt": forwarding_outcome.response_excerpt,
        }

        async with self._connection_pool.connection() as connection, connection.transaction():
            if forwarding_outcome.is_delivered:
                state_updated = await mark_message_delivered(
                    connection, claimed_message, forwarding_outcome.http_status or 200
                )
                event_types = [MessageEventType.DELIVERY_SUCCEEDED]
                log_message = "Lab result delivered"
            else:
                error_message = forwarding_outcome.error_message or "Delivery failed"
                outcome_detail["error"] = error_message
                attempts_exhausted = attempt_number >= claimed_message.max_attempts
                if forwarding_outcome.is_permanent_failure or attempts_exhausted:
                    outcome_detail["reason"] = (
                        "permanent_failure"
                        if forwarding_outcome.is_permanent_failure
                        else "retries_exhausted"
                    )
                    state_updated = await mark_message_dead_lettered(
                        connection, claimed_message, error_message, forwarding_outcome.http_status
                    )
                    event_types = [MessageEventType.DELIVERY_FAILED, MessageEventType.DEAD_LETTERED]
                    log_message = "Lab result dead-lettered"
                else:
                    retry_delay_seconds = self._retry_policy.next_delay_seconds(attempt_number)
                    outcome_detail["retry_delay_seconds"] = round(retry_delay_seconds, 2)
                    state_updated = await schedule_message_retry(
                        connection,
                        claimed_message,
                        retry_delay_seconds,
                        error_message,
                        forwarding_outcome.http_status,
                    )
                    event_types = [
                        MessageEventType.DELIVERY_FAILED,
                        MessageEventType.RETRY_SCHEDULED,
                    ]
                    log_message = "Lab result delivery failed; retry scheduled"

            if not state_updated:
                logger.warning(
                    "Delivery lease on message %s was lost before attempt %d was recorded; "
                    "another worker owns this message now",
                    claimed_message.inbound_message_id,
                    attempt_number,
                )
                return

            for event_type in event_types:
                await record_message_event(
                    connection,
                    claimed_message.inbound_message_id,
                    claimed_message.correlation_id,
                    event_type,
                    attempt_number=attempt_number,
                    detail=outcome_detail,
                )

        log_level = logging.INFO if forwarding_outcome.is_delivered else logging.WARNING
        logger.log(
            log_level,
            "%s: message %s (HL7 %s, order %s), attempt %d, HTTP %s",
            log_message,
            claimed_message.inbound_message_id,
            claimed_message.message_control_id,
            claimed_message.order_no,
            attempt_number,
            forwarding_outcome.http_status,
        )


def build_forwarding_worker(
    settings: Settings, connection_pool: AsyncConnectionPool
) -> ForwardingWorker:
    api_client = LabResultApiClient(
        api_url=settings.hl7_api_url,
        client_id=settings.hl7_int_client_id,
        hmac_secret=settings.hl7_api_hmac_secret.get_secret_value(),
        timeout_seconds=settings.hl7_api_timeout_seconds,
    )
    return ForwardingWorker(
        connection_pool=connection_pool,
        api_client=api_client,
        retry_policy=RetryPolicy(
            max_attempts=settings.delivery_max_attempts,
            backoff_base_seconds=settings.delivery_backoff_base_seconds,
            backoff_cap_seconds=settings.delivery_backoff_cap_seconds,
        ),
        batch_size=settings.delivery_batch_size,
        lease_seconds=settings.delivery_lease_seconds,
        poll_interval_seconds=settings.delivery_poll_interval_seconds,
    )
