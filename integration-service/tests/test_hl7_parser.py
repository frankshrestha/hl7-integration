import pytest

from hl7_integration.hl7.error_codes import Hl7ErrorCode
from hl7_integration.hl7.parser import (
    Hl7ParseError,
    ParsedMessage,
    find_first_segment,
    find_segments,
    parse_message,
    read_component,
    read_header,
    read_value,
)


def test_reads_header_fields(parsed_lab_result_message: ParsedMessage) -> None:
    header = read_header(parsed_lab_result_message)
    assert header.sending_application == "LAB"
    assert header.sending_facility == "HOSPITAL"
    assert header.receiving_application == "HMIS"
    assert header.message_type == "ORU"
    assert header.trigger_event == "R01"
    assert header.message_control_id == "MSG00001"
    assert header.processing_id == "P"
    assert header.version_id == "2.5"


def test_reads_components_of_regular_segments(parsed_lab_result_message: ParsedMessage) -> None:
    patient_segment = find_first_segment(parsed_lab_result_message, "PID")
    assert patient_segment is not None
    assert read_value(patient_segment.pid_5.xpn_1) == "DOE"
    assert read_value(patient_segment.pid_5.xpn_2) == "JOHN"
    assert read_value(patient_segment.pid_5.xpn_3) == ""
    assert read_component(patient_segment.pid_5, 2) == "JOHN"
    assert len(find_segments(parsed_lab_result_message, "OBX")) == 2


@pytest.mark.parametrize("segment_terminator", ["\r", "\n", "\r\n"])
def test_accepts_any_common_segment_terminator(
    lab_result_message_text: str, segment_terminator: str
) -> None:
    message_text = lab_result_message_text.strip("\r").replace("\r", segment_terminator)
    parsed_message = parse_message(message_text)
    assert [segment.name for segment in parsed_message.children] == [
        "MSH",
        "PID",
        "ORC",
        "OBR",
        "OBX",
        "OBX",
    ]


@pytest.mark.parametrize("payload", ["", "   ", "PID|1||PAT1", "this is not hl7"])
def test_rejects_payloads_without_header(payload: str) -> None:
    with pytest.raises(Hl7ParseError) as parse_error:
        parse_message(payload)
    assert parse_error.value.error_code is Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR
