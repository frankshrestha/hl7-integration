"""Maps a validated ORU^R01 message to the internal payload."""

import re
from dataclasses import dataclass
from datetime import datetime

from hl7apy.core import Segment
from hl7apy.exceptions import HL7apyException

from hl7_integration.hl7.parser import (
    ParsedMessage,
    find_first_segment,
    find_segments,
    read_header,
    read_value,
)
from hl7_integration.models.lab_result import (
    LabResultPayload,
    ObservationResult,
    Order,
    Patient,
)

# YYYYMMDD[HH[MM[SS]]][.ffff][+/-ZZZZ]
HL7_DATE_TIME_PATTERN = re.compile(
    r"^(?P<date_time>\d{8}(?:\d{2}(?:\d{2}(?:\d{2})?)?)?)(?:\.\d{1,4})?(?P<offset>[+-]\d{4})?$"
)


class LabResultMappingError(ValueError):
    """Raised when a message that passed validation still lacks data needed for mapping."""


@dataclass(frozen=True)
class TraceIdentifiers:
    """Identifiers stored with every message, including ones that are rejected."""

    message_control_id: str = ""
    sending_application: str = ""
    sending_facility: str = ""
    message_type: str = ""
    hl7_version: str = ""
    order_no: str = ""
    patient_external_id: str = ""


def map_lab_result(message: ParsedMessage) -> LabResultPayload:
    patient_segment = _require_segment(message, "PID")
    observation_request_segment = _require_segment(message, "OBR")
    common_order_segment = find_first_segment(message, "ORC")

    header = read_header(message)
    message_datetime = convert_hl7_datetime_to_iso(header.message_date_time)
    if message_datetime is None:
        raise LabResultMappingError("MSH-7 date/time of message is required for mapping")

    return LabResultPayload(
        message_id=header.message_control_id,
        message_type="^".join(filter(None, [header.message_type, header.trigger_event])) or None,
        message_datetime=message_datetime,
        patient=_map_patient(patient_segment),
        order=_map_order(observation_request_segment, common_order_segment),
        results=[
            _map_observation(observation_segment)
            for observation_segment in find_segments(message, "OBX")
        ],
    )


def extract_order_number(
    observation_request_segment: Segment | None, common_order_segment: Segment | None
) -> str:
    """Placer order number: OBR-2, falling back to ORC-2."""
    if observation_request_segment is not None:
        placer_order_number = read_value(observation_request_segment.obr_2.ei_1)
        if placer_order_number:
            return placer_order_number
    if common_order_segment is not None:
        return read_value(common_order_segment.orc_2.ei_1)
    return ""


def extract_trace_identifiers(message: ParsedMessage | None) -> TraceIdentifiers:
    """Best-effort read of identifiers; never fails, even for unsupported or broken messages."""
    if message is None:
        return TraceIdentifiers()
    try:
        header = read_header(message)
    except HL7apyException:
        return TraceIdentifiers()
    try:
        order_no = extract_order_number(
            find_first_segment(message, "OBR"), find_first_segment(message, "ORC")
        )
    except HL7apyException:
        order_no = ""
    try:
        patient_segment = find_first_segment(message, "PID")
        patient_external_id = read_value(patient_segment.pid_3.cx_1) if patient_segment else ""
    except HL7apyException:
        patient_external_id = ""
    return TraceIdentifiers(
        message_control_id=header.message_control_id,
        sending_application=header.sending_application,
        sending_facility=header.sending_facility,
        message_type="^".join(filter(None, [header.message_type, header.trigger_event])),
        hl7_version=header.version_id,
        order_no=order_no,
        patient_external_id=patient_external_id,
    )


def convert_hl7_date_to_iso(hl7_date: str) -> str | None:
    """Convert an HL7 DTM value (YYYYMMDD...) to an ISO date (YYYY-MM-DD)."""
    if len(hl7_date) < 8:
        return None
    return f"{hl7_date[0:4]}-{hl7_date[4:6]}-{hl7_date[6:8]}"


def convert_hl7_datetime_to_iso(hl7_date_time: str) -> str | None:
    """Convert an HL7 DTM value (YYYYMMDD[HH[MM[SS[.S]]]][+/-ZZZZ]) to ISO 8601."""
    match = HL7_DATE_TIME_PATTERN.match(hl7_date_time)
    if match is None:
        return None
    date_time_digits = match["date_time"].ljust(14, "0")
    try:
        parsed_date_time = datetime.strptime(date_time_digits, "%Y%m%d%H%M%S")
    except ValueError:
        return None
    iso_date_time = parsed_date_time.isoformat()
    if match["offset"]:
        iso_date_time += f"{match['offset'][:3]}:{match['offset'][3:]}"
    return iso_date_time


def _map_patient(patient_segment: Segment) -> Patient:
    return Patient(
        external_id=read_value(patient_segment.pid_3.cx_1),
        first_name=read_value(patient_segment.pid_5.xpn_2),
        last_name=read_value(patient_segment.pid_5.xpn_1),
        dob=convert_hl7_date_to_iso(read_value(patient_segment.pid_7.ts_1)),
        gender=read_value(patient_segment.pid_8) or None,
    )


def _map_order(observation_request_segment: Segment, common_order_segment: Segment | None) -> Order:
    return Order(
        order_no=extract_order_number(observation_request_segment, common_order_segment),
        service_code=read_value(observation_request_segment.obr_4.ce_1),
        service_name=read_value(observation_request_segment.obr_4.ce_2),
    )


def _map_observation(observation_segment: Segment) -> ObservationResult:
    set_id = read_value(observation_segment.obx_1)
    return ObservationResult(
        set_id=int(set_id) if set_id.isdigit() else None,
        code=read_value(observation_segment.obx_3.ce_1),
        name=read_value(observation_segment.obx_3.ce_2),
        value=read_value(observation_segment.obx_5),
        value_type=read_value(observation_segment.obx_2) or None,
        unit=read_value(observation_segment.obx_6.ce_1),
        reference_range=read_value(observation_segment.obx_7),
        flag=read_value(observation_segment.obx_8),
        result_status=read_value(observation_segment.obx_11) or None,
        observed_at=convert_hl7_datetime_to_iso(read_value(observation_segment.obx_14.ts_1)),
    )


def _require_segment(message: ParsedMessage, segment_id: str) -> Segment:
    segment = find_first_segment(message, segment_id)
    if segment is None:
        raise LabResultMappingError(f"Segment {segment_id} is required for mapping")
    return segment
