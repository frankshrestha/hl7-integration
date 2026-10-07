import logging
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from hl7_integration.database.inbound_message_repository import (
    list_dead_lettered_message_ids,
    requeue_dead_lettered_message,
    update_normalized_payload,
)
from hl7_integration.database.message_event_repository import record_message_event
from hl7_integration.mapping.remap import RemapError, remap_stored_message
from hl7_integration.models.message_status import MessageEventType

logger = logging.getLogger(__name__)


async def replay_dead_lettered_message(
    connection_pool: AsyncConnectionPool,
    inbound_message_id: UUID,
    max_attempts: int,
    requested_by: str,
) -> bool:
    """Re-queue one dead-lettered message."""
    async with connection_pool.connection() as connection, connection.transaction():
        requeued_message = await requeue_dead_lettered_message(
            connection, inbound_message_id, max_attempts
        )
        if requeued_message is None:
            return False
        replay_detail = {
            "requested_by": requested_by,
            "previous_error": requeued_message["last_error"],
        }
        try:
            normalized_payload = remap_stored_message(requeued_message["raw_payload"])
        except RemapError as mapping_error:
            replay_detail["remap_error"] = str(mapping_error)
        else:
            await update_normalized_payload(connection, inbound_message_id, normalized_payload)
        await record_message_event(
            connection,
            inbound_message_id,
            requeued_message["correlation_id"],
            MessageEventType.REPLAYED,
            detail=replay_detail,
        )
    logger.info(
        "Dead-lettered message %s re-queued (requested by %s)", inbound_message_id, requested_by
    )
    return True


async def replay_all_dead_lettered_messages(
    connection_pool: AsyncConnectionPool, max_attempts: int, requested_by: str
) -> int:
    async with connection_pool.connection() as connection:
        dead_lettered_message_ids = await list_dead_lettered_message_ids(connection)
    replayed_count = 0
    for inbound_message_id in dead_lettered_message_ids:
        if await replay_dead_lettered_message(
            connection_pool, inbound_message_id, max_attempts, requested_by
        ):
            replayed_count += 1
    return replayed_count
