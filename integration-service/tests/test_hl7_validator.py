import pytest

from hl7_integration.hl7.error_codes import Hl7ErrorCode
from hl7_integration.hl7.parser import parse_message
from hl7_integration.hl7.validator import validate_lab_result_message

HEADER = "MSH|^~\\&|LAB|HOSPITAL|HMIS|HOSPITAL|20261001103000||ORU^R01|MSG00001|P|2.5"
PATIENT = "PID|1||PAT00001||DOE^JOHN||19900101|M"
ORDER = "ORC|RE|ORD00001"
REQUEST = "OBR|1|ORD00001||CBC^Complete Blood Count"
OBSERVATION = "OBX|1|NM|HB^Hemoglobin||13.5|g/dL|12-16|N|||F"


def error_codes_for(*segments: str) -> list[Hl7ErrorCode]:
    issues = validate_lab_result_message(parse_message("\r".join(segments)))
    return [issue.error_code for issue in issues]


@pytest.mark.parametrize(
    ("header", "expected_code"),
    [
        (HEADER.replace("ORU^R01", "ADT^A01"), Hl7ErrorCode.UNSUPPORTED_MESSAGE_TYPE),
        (HEADER.replace("ORU^R01", "ORU^R30"), Hl7ErrorCode.UNSUPPORTED_EVENT_CODE),
        (HEADER.replace("|2.5", "|2.3"), Hl7ErrorCode.UNSUPPORTED_VERSION_ID),
        (HEADER.replace("|P|", "|X|"), Hl7ErrorCode.UNSUPPORTED_PROCESSING_ID),
        (HEADER.replace("MSG00001", ""), Hl7ErrorCode.REQUIRED_FIELD_MISSING),
        (HEADER.replace("20261001103000", ""), Hl7ErrorCode.REQUIRED_FIELD_MISSING),
        (HEADER.replace("20261001103000", "20261341"), Hl7ErrorCode.DATA_TYPE_ERROR),
    ],
)
def test_header_rules(header: str, expected_code: Hl7ErrorCode) -> None:
    assert error_codes_for(header, PATIENT, ORDER, REQUEST, OBSERVATION) == [expected_code]


@pytest.mark.parametrize("missing_segment", [PATIENT, REQUEST, OBSERVATION])
def test_required_segments(missing_segment: str) -> None:
    segments = [
        segment
        for segment in (HEADER, PATIENT, ORDER, REQUEST, OBSERVATION)
        if segment != missing_segment
    ]
    assert Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR in error_codes_for(*segments)


def test_rejects_multiple_orders() -> None:
    codes = error_codes_for(HEADER, PATIENT, ORDER, REQUEST, OBSERVATION, REQUEST, OBSERVATION)
    assert codes == [Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR]


def test_rejects_observation_before_request() -> None:
    codes = error_codes_for(HEADER, PATIENT, OBSERVATION, ORDER, REQUEST)
    assert codes == [Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR]
