from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from hl7_integration.models.message_status import MessageEventType


async def record_message_event(
    connection: AsyncConnection[Any],
    inbound_message_id: UUID,
    correlation_id: UUID,
    event_type: MessageEventType,
    attempt_number: int | None = None,
    detail: dict[str, Any] | None = None,
) -> None:
    await connection.execute(
        """
        INSERT INTO message_events
            (inbound_message_id, correlation_id, event_type, attempt_number, detail)
        VALUES (%s, %s, %s, %s, %s)
        """,
        (inbound_message_id, correlation_id, event_type.value, attempt_number, Jsonb(detail or {})),
    )


async def list_message_events(
    connection: AsyncConnection[Any], inbound_message_id: UUID
) -> list[dict[str, Any]]:
    cursor = await connection.execute(
        """
        SELECT id, correlation_id, event_type, attempt_number, detail, created_at
        FROM message_events
        WHERE inbound_message_id = %s
        ORDER BY created_at, id
        """,
        (inbound_message_id,),
    )
    return await cursor.fetchall()
