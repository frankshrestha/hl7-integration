import re
from dataclasses import dataclass
from datetime import datetime

from hl7apy.core import Segment
from hl7apy.exceptions import HL7apyException
from hl7apy.validation import Validator

from hl7_integration.hl7.error_codes import Hl7ErrorCode
from hl7_integration.hl7.parser import (
    ParsedMessage,
    find_first_segment,
    find_segments,
    parse_grouped_message,
    read_header,
    read_value,
)

SUPPORTED_MESSAGE_TYPE = "ORU"
SUPPORTED_TRIGGER_EVENT = "R01"
SUPPORTED_VERSIONS = frozenset({"2.5", "2.5.1"})
SUPPORTED_PROCESSING_IDS = frozenset({"P", "T", "D"})
SUPPORTED_ADMINISTRATIVE_SEX_CODES = frozenset({"M", "F", "O"})

SPEC_FIELD_PATTERN = re.compile(r"(\w+)\.\1_(\d+)$")


@dataclass(frozen=True)
class ValidationIssue:
    error_code: Hl7ErrorCode
    message: str
    segment_id: str = ""
    segment_sequence: int | None = None
    field_position: int | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "segment_id": self.segment_id,
            "segment_sequence": self.segment_sequence,
            "field_position": self.field_position,
        }


def validate_lab_result_message(message: ParsedMessage) -> list[ValidationIssue]:
    """Return every problem found; an empty list means the message is acceptable."""
    try:
        header_issues = _validate_header(message)
        if header_issues:
            return header_issues

        issues = _validate_against_spec(message)
        issues.extend(_validate_profile(message))
        return issues
    except HL7apyException as read_error:
        return [
            ValidationIssue(
                Hl7ErrorCode.DATA_TYPE_ERROR, f"Message content could not be read: {read_error}"
            )
        ]


def is_valid_hl7_date(value: str) -> bool:
    date_part = value[:8]
    if len(date_part) != 8 or not date_part.isdigit():
        return False
    try:
        datetime.strptime(date_part, "%Y%m%d")
    except ValueError:
        return False
    return True


def _validate_header(message: ParsedMessage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    header = read_header(message)
    if not header.message_type:
        issues.append(_missing_field("MSH", 9, "MSH-9 message type is required"))
    elif header.message_type != SUPPORTED_MESSAGE_TYPE:
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.UNSUPPORTED_MESSAGE_TYPE,
                f"Message type {header.message_type} is not supported; expected ORU",
                "MSH",
                1,
                9,
            )
        )
    elif header.trigger_event != SUPPORTED_TRIGGER_EVENT:
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.UNSUPPORTED_EVENT_CODE,
                f"Trigger event {header.trigger_event or '(empty)'} is not supported; expected R01",
                "MSH",
                1,
                9,
            )
        )

    if header.processing_id and header.processing_id not in SUPPORTED_PROCESSING_IDS:
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.UNSUPPORTED_PROCESSING_ID,
                f"Processing id {header.processing_id} is not supported",
                "MSH",
                1,
                11,
            )
        )

    if header.version_id not in SUPPORTED_VERSIONS:
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.UNSUPPORTED_VERSION_ID,
                f"HL7 version {header.version_id} is not supported; expected 2.5",
                "MSH",
                1,
                12,
            )
        )
    return issues


def _validate_against_spec(message: ParsedMessage) -> list[ValidationIssue]:
    try:
        Validator.validate(parse_grouped_message(message))
    except HL7apyException as spec_error:
        return [_issue_from_spec_error(str(spec_error))]
    return []


def _issue_from_spec_error(error_message: str) -> ValidationIssue:
    if error_message.startswith("Missing required child"):
        field_match = SPEC_FIELD_PATTERN.search(error_message)
        if field_match:
            return _missing_field(field_match[1], int(field_match[2]), error_message)
        segment_id = error_message.rsplit(".", 1)[-1]
        return ValidationIssue(Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR, error_message, segment_id)
    if error_message.startswith("Datatype"):
        return ValidationIssue(Hl7ErrorCode.DATA_TYPE_ERROR, error_message)
    return ValidationIssue(Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR, error_message)


def _validate_profile(message: ParsedMessage) -> list[ValidationIssue]:
    issues = _validate_segment_structure(message)

    message_date_time = read_header(message).message_date_time
    if message_date_time and not is_valid_hl7_date(message_date_time):
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.DATA_TYPE_ERROR,
                f"MSH-7 {message_date_time} is not a valid HL7 date/time",
                "MSH",
                1,
                7,
            )
        )

    patient_segment = find_first_segment(message, "PID")
    if patient_segment is not None:
        issues.extend(_validate_patient(patient_segment))

    observation_request_segment = find_first_segment(message, "OBR")
    if observation_request_segment is not None:
        has_order_number = bool(read_value(observation_request_segment.obr_2.ei_1)) or any(
            read_value(common_order_segment.orc_2.ei_1)
            for common_order_segment in find_segments(message, "ORC")
        )
        if not has_order_number:
            issues.append(_missing_field("OBR", 2, "Order number is required in OBR-2 or ORC-2"))

    for sequence_number, observation_segment in enumerate(find_segments(message, "OBX"), 1):
        if not read_value(observation_segment.obx_5).strip():
            issues.append(
                _missing_field("OBX", 5, "OBX-5 observation value is required", sequence_number)
            )
    return issues


def _validate_segment_structure(message: ParsedMessage) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    segment_ids = [segment.name for segment in message.children]

    for required_segment_id in ("PID", "OBX"):
        if required_segment_id not in segment_ids:
            issues.append(
                ValidationIssue(
                    Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR,
                    f"Required segment {required_segment_id} is missing",
                    required_segment_id,
                )
            )

    if segment_ids.count("OBR") > 1:
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR,
                "Only one OBR segment (one order) is supported per message",
                "OBR",
            )
        )

    if "OBR" in segment_ids and "OBX" in segment_ids[: segment_ids.index("OBR")]:
        issues.append(
            ValidationIssue(Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR, "OBX must appear after OBR", "OBX")
        )
    return issues


def _validate_patient(patient_segment: Segment) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    date_of_birth = read_value(patient_segment.pid_7.ts_1)
    if date_of_birth and not is_valid_hl7_date(date_of_birth):
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.DATA_TYPE_ERROR,
                f"PID-7 date of birth {date_of_birth} is not a valid YYYYMMDD date",
                "PID",
                1,
                7,
            )
        )

    administrative_sex = read_value(patient_segment.pid_8)
    if administrative_sex and administrative_sex not in SUPPORTED_ADMINISTRATIVE_SEX_CODES:
        issues.append(
            ValidationIssue(
                Hl7ErrorCode.TABLE_VALUE_NOT_FOUND,
                f"PID-8 administrative sex {administrative_sex} is not supported; "
                "expected M, F or O",
                "PID",
                1,
                8,
            )
        )
    return issues


def _missing_field(
    segment_id: str, field_position: int, message: str, segment_sequence: int = 1
) -> ValidationIssue:
    return ValidationIssue(
        Hl7ErrorCode.REQUIRED_FIELD_MISSING,
        message,
        segment_id,
        segment_sequence,
        field_position,
    )
