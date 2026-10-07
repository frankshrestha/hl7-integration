import uuid
from collections.abc import Sequence
from datetime import datetime
from enum import StrEnum

from hl7apy.consts import VALIDATION_LEVEL
from hl7apy.core import Message

from hl7_integration.hl7.error_codes import Hl7ErrorCode
from hl7_integration.hl7.escaping import escape_value
from hl7_integration.hl7.parser import ParsedMessage, read_header
from hl7_integration.hl7.validator import ValidationIssue

SEGMENT_TERMINATOR = "\r"
ACK_STRUCTURE_VERSION = "2.5"
DEFAULT_VERSION_ID = "2.5"
DEFAULT_PROCESSING_ID = "P"


class AcknowledgmentCode(StrEnum):
    ACCEPTED = "AA"  # Message accepted.
    ERROR = "AE"  # Message is invalid.
    REJECTED = "AR"  # Temporary failure.


def build_acknowledgment(
    acknowledgment_code: AcknowledgmentCode,
    original_message: ParsedMessage | None,
    text_message: str,
    issues: Sequence[ValidationIssue] = (),
    local_application: str = "HL7_INT",
    local_facility: str = "",
    acknowledged_at: datetime | None = None,
) -> str:
    header = read_header(original_message) if original_message is not None else None

    acknowledgment = Message(
        "ACK", version=ACK_STRUCTURE_VERSION, validation_level=VALIDATION_LEVEL.TOLERANT
    )
    message_header = acknowledgment.msh
    message_header.msh_3 = escape_value(
        (header.receiving_application if header else "") or local_application
    )
    message_header.msh_4 = escape_value(
        (header.receiving_facility if header else "") or local_facility
    )
    message_header.msh_5 = escape_value(header.sending_application if header else "")
    message_header.msh_6 = escape_value(header.sending_facility if header else "")
    message_header.msh_7 = (acknowledged_at or datetime.now()).strftime("%Y%m%d%H%M%S")
    trigger_event = escape_value((header.trigger_event if header else "") or "R01")
    message_header.msh_9 = f"ACK^{trigger_event}^ACK"
    message_header.msh_10 = f"ACK{uuid.uuid4().hex[:17].upper()}"
    message_header.msh_11 = escape_value(
        (header.processing_id if header else "") or DEFAULT_PROCESSING_ID
    )
    message_header.msh_12 = escape_value(
        (header.version_id if header else "") or DEFAULT_VERSION_ID
    )

    acknowledgment.msa.msa_1 = acknowledgment_code.value
    acknowledgment.msa.msa_2 = escape_value(header.message_control_id if header else "")
    acknowledgment.msa.msa_3 = escape_value(text_message)

    for issue in issues:
        _add_error_segment(acknowledgment, issue)

    return acknowledgment.to_er7() + SEGMENT_TERMINATOR


def build_internal_error_issue(message: str) -> ValidationIssue:
    return ValidationIssue(Hl7ErrorCode.APPLICATION_INTERNAL_ERROR, message)


def _add_error_segment(acknowledgment: Message, issue: ValidationIssue) -> None:
    error_segment = acknowledgment.add_segment("ERR")
    error_location = "^".join(
        [
            escape_value(issue.segment_id),
            str(issue.segment_sequence) if issue.segment_sequence is not None else "",
            str(issue.field_position) if issue.field_position is not None else "",
        ]
    ).rstrip("^")
    if error_location:
        error_segment.err_2 = error_location
    error_segment.err_3 = f"{issue.error_code.value}^{issue.error_code.description}^HL70357"
    error_segment.err_4 = "E"
    error_segment.err_8 = escape_value(issue.message)
