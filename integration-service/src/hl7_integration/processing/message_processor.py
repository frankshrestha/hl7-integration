"""Processes one raw HL7 message: parse, validate, map, save to the database.

ACK semantics (HL7 original mode):
- AA: the message is valid.
- AE: the message is invalid.
- AR: temporary failure.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from psycopg_pool import AsyncConnectionPool

from hl7_integration.database.inbound_message_repository import (
    NewInboundMessage,
    find_accepted_message_by_control_id,
    insert_queued_message,
    insert_rejected_message,
)
from hl7_integration.database.message_event_repository import record_message_event
from hl7_integration.hl7.ack import (
    AcknowledgmentCode,
    build_acknowledgment,
    build_internal_error_issue,
)
from hl7_integration.hl7.error_codes import Hl7ErrorCode
from hl7_integration.hl7.parser import (
    Hl7ParseError,
    ParsedMessage,
    parse_message,
    try_parse_message,
)
from hl7_integration.hl7.validator import ValidationIssue, validate_lab_result_message
from hl7_integration.mapping.lab_result_mapper import extract_trace_identifiers, map_lab_result
from hl7_integration.models.message_status import MessageEventType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingResult:
    acknowledgment_code: AcknowledgmentCode
    acknowledgment_message: str
    correlation_id: UUID
    inbound_message_id: UUID | None


class MessageProcessor:
    def __init__(
        self,
        connection_pool: AsyncConnectionPool,
        max_delivery_attempts: int,
        local_application: str,
        local_facility: str,
    ) -> None:
        self._connection_pool = connection_pool
        self._max_delivery_attempts = max_delivery_attempts
        self._local_application = local_application
        self._local_facility = local_facility

    async def process_message(
        self, raw_message: str, correlation_id: UUID | None = None
    ) -> ProcessingResult:
        correlation_id = correlation_id or uuid.uuid4()
        received_at = datetime.now(UTC)
        logger.info(
            "HL7 message received (correlation_id=%s, %d bytes)",
            correlation_id,
            len(raw_message),
        )
        try:
            return await self._process(raw_message, correlation_id, received_at)
        except Exception:
            logger.exception(
                "Temporary failure while accepting HL7 message (correlation_id=%s)",
                correlation_id,
            )
            return self._acknowledge(
                AcknowledgmentCode.REJECTED,
                try_parse_message(raw_message),
                "Temporary processing failure; please resend later",
                correlation_id,
                None,
                [build_internal_error_issue("Message could not be stored; retry later")],
            )

    async def _process(
        self, raw_message: str, correlation_id: UUID, received_at: datetime
    ) -> ProcessingResult:
        try:
            parsed_message = parse_message(raw_message)
        except Hl7ParseError as parse_error:
            issue = ValidationIssue(parse_error.error_code, str(parse_error), "MSH")
            return await self._reject(raw_message, None, correlation_id, received_at, [issue])

        validation_issues = validate_lab_result_message(parsed_message)
        if validation_issues:
            return await self._reject(
                raw_message,
                parsed_message,
                correlation_id,
                received_at,
                validation_issues,
            )

        normalized_payload = map_lab_result(parsed_message).model_dump(mode="json")
        new_message = self._build_new_message(
            raw_message,
            parsed_message,
            correlation_id,
            received_at,
            normalized_payload=normalized_payload,
        )

        async with self._connection_pool.connection() as connection, connection.transaction():
            was_inserted = await insert_queued_message(connection, new_message)
            if was_inserted:
                await record_message_event(
                    connection,
                    new_message.inbound_message_id,
                    correlation_id,
                    MessageEventType.RECEIVED,
                )
                await record_message_event(
                    connection,
                    new_message.inbound_message_id,
                    correlation_id,
                    MessageEventType.QUEUED,
                )
                existing_message = None
            else:
                existing_message = await find_accepted_message_by_control_id(
                    connection,
                    new_message.sending_application,
                    new_message.sending_facility,
                    new_message.message_control_id or "",
                )
                if existing_message is None:
                    raise RuntimeError("Duplicate detected but the original message was not found")
                if existing_message["payload_sha256"] == new_message.payload_sha256:
                    await record_message_event(
                        connection,
                        existing_message["id"],
                        correlation_id,
                        MessageEventType.DUPLICATE_RECEIVED,
                        detail={
                            "original_correlation_id": str(existing_message["correlation_id"]),
                            "current_status": existing_message["status"],
                        },
                    )

        if existing_message is None:
            logger.info(
                "HL7 message %s (order %s) accepted and queued for delivery as %s",
                new_message.message_control_id,
                new_message.order_no,
                new_message.inbound_message_id,
            )
            return self._acknowledge(
                AcknowledgmentCode.ACCEPTED,
                parsed_message,
                "Message accepted",
                correlation_id,
                new_message.inbound_message_id,
            )

        if existing_message["payload_sha256"] == new_message.payload_sha256:
            logger.info(
                "Duplicate HL7 message %s acknowledged without re-queueing (original %s)",
                new_message.message_control_id,
                existing_message["id"],
            )
            return self._acknowledge(
                AcknowledgmentCode.ACCEPTED,
                parsed_message,
                "Duplicate message; already accepted",
                correlation_id,
                existing_message["id"],
            )

        conflict_issue = ValidationIssue(
            Hl7ErrorCode.DUPLICATE_KEY_IDENTIFIER,
            "Message control id was already used for a message with different content",
            "MSH",
            1,
            10,
        )
        return await self._reject(
            raw_message, parsed_message, correlation_id, received_at, [conflict_issue]
        )

    async def _reject(
        self,
        raw_message: str,
        parsed_message: ParsedMessage | None,
        correlation_id: UUID,
        received_at: datetime,
        validation_issues: list[ValidationIssue],
    ) -> ProcessingResult:
        serialized_issues = [issue.to_dict() for issue in validation_issues]
        new_message = self._build_new_message(
            raw_message,
            parsed_message,
            correlation_id,
            received_at,
            validation_errors=serialized_issues,
        )
        inbound_message_id: UUID | None = new_message.inbound_message_id
        try:
            async with self._connection_pool.connection() as connection, connection.transaction():
                await insert_rejected_message(connection, new_message)
                await record_message_event(
                    connection,
                    new_message.inbound_message_id,
                    correlation_id,
                    MessageEventType.RECEIVED,
                )
                await record_message_event(
                    connection,
                    new_message.inbound_message_id,
                    correlation_id,
                    MessageEventType.VALIDATION_FAILED,
                    detail={"issues": serialized_issues},
                )
        except Exception:
            # The message is invalid regardless of storage, so AE is still the right answer.
            logger.exception("Could not store rejected message for audit")
            inbound_message_id = None

        logger.warning(
            "HL7 message %s rejected (correlation_id=%s): %s",
            new_message.message_control_id,
            correlation_id,
            "; ".join(issue.message for issue in validation_issues),
        )
        return self._acknowledge(
            AcknowledgmentCode.ERROR,
            parsed_message,
            "Message rejected: validation failed",
            correlation_id,
            inbound_message_id,
            validation_issues,
        )

    def _build_new_message(
        self,
        raw_message: str,
        parsed_message: ParsedMessage | None,
        correlation_id: UUID,
        received_at: datetime,
        normalized_payload: dict[str, Any] | None = None,
        validation_errors: list[dict[str, Any]] | None = None,
    ) -> NewInboundMessage:
        trace_identifiers = extract_trace_identifiers(parsed_message)
        return NewInboundMessage(
            inbound_message_id=uuid.uuid4(),
            correlation_id=correlation_id,
            message_control_id=trace_identifiers.message_control_id or None,
            sending_application=trace_identifiers.sending_application,
            sending_facility=trace_identifiers.sending_facility,
            message_type=trace_identifiers.message_type or None,
            hl7_version=trace_identifiers.hl7_version or None,
            order_no=trace_identifiers.order_no or None,
            patient_external_id=trace_identifiers.patient_external_id or None,
            raw_payload=raw_message,
            payload_sha256=hashlib.sha256(raw_message.encode()).hexdigest(),
            normalized_payload=normalized_payload,
            validation_errors=validation_errors,
            max_attempts=self._max_delivery_attempts,
            received_at=received_at,
        )

    def _acknowledge(
        self,
        acknowledgment_code: AcknowledgmentCode,
        parsed_message: ParsedMessage | None,
        text_message: str,
        correlation_id: UUID,
        inbound_message_id: UUID | None,
        issues: list[ValidationIssue] | None = None,
    ) -> ProcessingResult:
        acknowledgment_message = build_acknowledgment(
            acknowledgment_code,
            parsed_message,
            text_message,
            issues or [],
            local_application=self._local_application,
            local_facility=self._local_facility,
        )
        return ProcessingResult(
            acknowledgment_code=acknowledgment_code,
            acknowledgment_message=acknowledgment_message,
            correlation_id=correlation_id,
            inbound_message_id=inbound_message_id,
        )
