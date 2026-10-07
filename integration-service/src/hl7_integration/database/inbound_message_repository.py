from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import AsyncConnection
from psycopg.types.json import Jsonb

from hl7_integration.models.message_status import MessageStatus

MESSAGE_SUMMARY_COLUMNS = """
    id, correlation_id, message_control_id, sending_application, sending_facility,
    message_type, hl7_version, order_no, patient_external_id, payload_sha256,
    normalized_payload, status, ack_code, validation_errors, attempt_count, max_attempts,
    next_attempt_at, locked_until, last_error, last_http_status, received_at, queued_at,
    processed_at, dead_lettered_at, updated_at
"""


@dataclass(frozen=True)
class NewInboundMessage:
    inbound_message_id: UUID
    correlation_id: UUID
    message_control_id: str | None
    sending_application: str
    sending_facility: str
    message_type: str | None
    hl7_version: str | None
    order_no: str | None
    patient_external_id: str | None
    raw_payload: str
    payload_sha256: str
    normalized_payload: dict[str, Any] | None
    validation_errors: list[dict[str, Any]] | None
    max_attempts: int
    received_at: datetime


@dataclass(frozen=True)
class ClaimedMessage:
    inbound_message_id: UUID
    correlation_id: UUID
    message_control_id: str
    order_no: str | None
    normalized_payload: dict[str, Any]
    attempt_count: int
    max_attempts: int


async def insert_queued_message(
    connection: AsyncConnection[Any], new_message: NewInboundMessage
) -> bool:
    """Insert an accepted message as pending."""
    cursor = await connection.execute(
        """
        INSERT INTO inbound_messages (
            id, correlation_id, message_control_id, sending_application, sending_facility,
            message_type, hl7_version, order_no, patient_external_id, raw_payload,
            payload_sha256, normalized_payload, status, ack_code, max_attempts,
            next_attempt_at, received_at, queued_at
        )
        VALUES (
            %(id)s, %(correlation_id)s, %(message_control_id)s, %(sending_application)s,
            %(sending_facility)s, %(message_type)s, %(hl7_version)s,
            %(order_no)s, %(patient_external_id)s, %(raw_payload)s, %(payload_sha256)s,
            %(normalized_payload)s, %(status)s, 'AA', %(max_attempts)s, now(),
            %(received_at)s, now()
        )
        ON CONFLICT (sending_application, sending_facility, message_control_id)
            WHERE status <> 'rejected'
            DO NOTHING
        RETURNING id
        """,
        _insert_parameters(new_message, MessageStatus.PENDING),
    )
    return await cursor.fetchone() is not None


async def insert_rejected_message(
    connection: AsyncConnection[Any], new_message: NewInboundMessage
) -> None:
    await connection.execute(
        """
        INSERT INTO inbound_messages (
            id, correlation_id, message_control_id, sending_application, sending_facility,
            message_type, hl7_version, order_no, patient_external_id, raw_payload,
            payload_sha256, validation_errors, status, ack_code, max_attempts, received_at,
            processed_at
        )
        VALUES (
            %(id)s, %(correlation_id)s, %(message_control_id)s, %(sending_application)s,
            %(sending_facility)s, %(message_type)s, %(hl7_version)s,
            %(order_no)s, %(patient_external_id)s, %(raw_payload)s, %(payload_sha256)s,
            %(validation_errors)s, %(status)s, 'AE', %(max_attempts)s, %(received_at)s, now()
        )
        """,
        _insert_parameters(new_message, MessageStatus.REJECTED),
    )


async def find_accepted_message_by_control_id(
    connection: AsyncConnection[Any],
    sending_application: str,
    sending_facility: str,
    message_control_id: str,
) -> dict[str, Any] | None:
    cursor = await connection.execute(
        f"""
        SELECT {MESSAGE_SUMMARY_COLUMNS}
        FROM inbound_messages
        WHERE sending_application = %s
          AND sending_facility = %s
          AND message_control_id = %s
          AND status <> 'rejected'
        """,
        (sending_application, sending_facility, message_control_id),
    )
    return await cursor.fetchone()


async def find_accepted_messages_by_control_ids(
    connection: AsyncConnection[Any], message_control_ids: list[str]
) -> dict[str, list[dict[str, Any]]]:
    cursor = await connection.execute(
        """
        SELECT id, correlation_id, message_control_id, raw_payload, normalized_payload
        FROM inbound_messages
        WHERE message_control_id = ANY(%s) AND status <> 'rejected'
        ORDER BY received_at
        """,
        (message_control_ids,),
    )
    messages_by_control_id: dict[str, list[dict[str, Any]]] = {}
    for row in await cursor.fetchall():
        messages_by_control_id.setdefault(row["message_control_id"], []).append(row)
    return messages_by_control_id


async def find_message_by_id(
    connection: AsyncConnection[Any], inbound_message_id: UUID
) -> dict[str, Any] | None:
    cursor = await connection.execute(
        f"SELECT {MESSAGE_SUMMARY_COLUMNS}, raw_payload FROM inbound_messages WHERE id = %s",
        (inbound_message_id,),
    )
    return await cursor.fetchone()


async def list_messages(
    connection: AsyncConnection[Any],
    status: MessageStatus | None = None,
    message_control_id: str | None = None,
    order_no: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    cursor = await connection.execute(
        f"""
        SELECT {MESSAGE_SUMMARY_COLUMNS}
        FROM inbound_messages
        WHERE (%(status)s::text IS NULL OR status = %(status)s)
          AND (%(message_control_id)s::text IS NULL OR message_control_id = %(message_control_id)s)
          AND (%(order_no)s::text IS NULL OR order_no = %(order_no)s)
        ORDER BY received_at DESC
        LIMIT %(limit)s
        """,
        {
            "status": status.value if status else None,
            "message_control_id": message_control_id,
            "order_no": order_no,
            "limit": limit,
        },
    )
    return await cursor.fetchall()


async def claim_due_messages(
    connection: AsyncConnection[Any], batch_size: int, lease_seconds: float
) -> list[ClaimedMessage]:
    cursor = await connection.execute(
        """
        WITH due_messages AS (
            SELECT id
            FROM inbound_messages
            WHERE (status IN ('pending', 'retrying') AND next_attempt_at <= now())
               OR (status = 'in_flight' AND locked_until < now())
            ORDER BY next_attempt_at NULLS FIRST
            LIMIT %(batch_size)s
            FOR UPDATE SKIP LOCKED
        )
        UPDATE inbound_messages AS message
        SET status = 'in_flight',
            locked_until = now() + make_interval(secs => %(lease_seconds)s),
            attempt_count = message.attempt_count + 1,
            updated_at = now()
        FROM due_messages
        WHERE message.id = due_messages.id
        RETURNING message.id, message.correlation_id, message.message_control_id,
                  message.order_no, message.normalized_payload, message.attempt_count,
                  message.max_attempts
        """,
        {"batch_size": batch_size, "lease_seconds": lease_seconds},
    )
    return [
        ClaimedMessage(
            inbound_message_id=row["id"],
            correlation_id=row["correlation_id"],
            message_control_id=row["message_control_id"],
            order_no=row["order_no"],
            normalized_payload=row["normalized_payload"],
            attempt_count=row["attempt_count"],
            max_attempts=row["max_attempts"],
        )
        for row in await cursor.fetchall()
    ]


async def mark_message_delivered(
    connection: AsyncConnection[Any], claimed_message: ClaimedMessage, http_status: int
) -> bool:
    cursor = await connection.execute(
        """
        UPDATE inbound_messages
        SET status = 'delivered', processed_at = now(), locked_until = NULL,
            next_attempt_at = NULL, last_http_status = %s, last_error = NULL, updated_at = now()
        WHERE id = %s AND status = 'in_flight' AND attempt_count = %s
        """,
        (http_status, claimed_message.inbound_message_id, claimed_message.attempt_count),
    )
    return cursor.rowcount == 1


async def schedule_message_retry(
    connection: AsyncConnection[Any],
    claimed_message: ClaimedMessage,
    retry_delay_seconds: float,
    error_message: str,
    http_status: int | None,
) -> bool:
    cursor = await connection.execute(
        """
        UPDATE inbound_messages
        SET status = 'retrying',
            next_attempt_at = now() + make_interval(secs => %s),
            locked_until = NULL, last_error = %s, last_http_status = %s, updated_at = now()
        WHERE id = %s AND status = 'in_flight' AND attempt_count = %s
        """,
        (
            retry_delay_seconds,
            error_message,
            http_status,
            claimed_message.inbound_message_id,
            claimed_message.attempt_count,
        ),
    )
    return cursor.rowcount == 1


async def mark_message_dead_lettered(
    connection: AsyncConnection[Any],
    claimed_message: ClaimedMessage,
    error_message: str,
    http_status: int | None,
) -> bool:
    cursor = await connection.execute(
        """
        UPDATE inbound_messages
        SET status = 'dead_lettered', dead_lettered_at = now(), next_attempt_at = NULL,
            locked_until = NULL, last_error = %s, last_http_status = %s, updated_at = now()
        WHERE id = %s AND status = 'in_flight' AND attempt_count = %s
        """,
        (
            error_message,
            http_status,
            claimed_message.inbound_message_id,
            claimed_message.attempt_count,
        ),
    )
    return cursor.rowcount == 1


async def requeue_dead_lettered_message(
    connection: AsyncConnection[Any], inbound_message_id: UUID, max_attempts: int
) -> dict[str, Any] | None:
    cursor = await connection.execute(
        """
        UPDATE inbound_messages
        SET status = 'pending', attempt_count = 0, max_attempts = %s, next_attempt_at = now(),
            dead_lettered_at = NULL, updated_at = now()
        WHERE id = %s AND status = 'dead_lettered'
        RETURNING id, correlation_id, last_error, raw_payload
        """,
        (max_attempts, inbound_message_id),
    )
    return await cursor.fetchone()


async def update_normalized_payload(
    connection: AsyncConnection[Any], inbound_message_id: UUID, normalized_payload: dict[str, Any]
) -> None:
    await connection.execute(
        "UPDATE inbound_messages SET normalized_payload = %s, updated_at = now() WHERE id = %s",
        (Jsonb(normalized_payload), inbound_message_id),
    )


async def list_dead_lettered_message_ids(connection: AsyncConnection[Any]) -> list[UUID]:
    cursor = await connection.execute(
        "SELECT id FROM inbound_messages WHERE status = 'dead_lettered' ORDER BY dead_lettered_at"
    )
    return [row["id"] for row in await cursor.fetchall()]


def _insert_parameters(new_message: NewInboundMessage, status: MessageStatus) -> dict[str, Any]:
    return {
        "id": new_message.inbound_message_id,
        "correlation_id": new_message.correlation_id,
        "message_control_id": new_message.message_control_id,
        "sending_application": new_message.sending_application,
        "sending_facility": new_message.sending_facility,
        "message_type": new_message.message_type,
        "hl7_version": new_message.hl7_version,
        "order_no": new_message.order_no,
        "patient_external_id": new_message.patient_external_id,
        "raw_payload": new_message.raw_payload,
        "payload_sha256": new_message.payload_sha256,
        "normalized_payload": (
            Jsonb(new_message.normalized_payload) if new_message.normalized_payload else None
        ),
        "validation_errors": (
            Jsonb(new_message.validation_errors) if new_message.validation_errors else None
        ),
        "status": status.value,
        "max_attempts": new_message.max_attempts,
        "received_at": new_message.received_at,
    }
