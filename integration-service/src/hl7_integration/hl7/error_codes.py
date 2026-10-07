from enum import StrEnum


class Hl7ErrorCode(StrEnum):
    SEGMENT_SEQUENCE_ERROR = "100"
    REQUIRED_FIELD_MISSING = "101"
    DATA_TYPE_ERROR = "102"
    TABLE_VALUE_NOT_FOUND = "103"
    UNSUPPORTED_MESSAGE_TYPE = "200"
    UNSUPPORTED_EVENT_CODE = "201"
    UNSUPPORTED_PROCESSING_ID = "202"
    UNSUPPORTED_VERSION_ID = "203"
    DUPLICATE_KEY_IDENTIFIER = "205"
    APPLICATION_INTERNAL_ERROR = "207"

    @property
    def description(self) -> str:
        return HL7_ERROR_CODE_DESCRIPTIONS[self]


HL7_ERROR_CODE_DESCRIPTIONS = {
    Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR: "Segment sequence error",
    Hl7ErrorCode.REQUIRED_FIELD_MISSING: "Required field missing",
    Hl7ErrorCode.DATA_TYPE_ERROR: "Data type error",
    Hl7ErrorCode.TABLE_VALUE_NOT_FOUND: "Table value not found",
    Hl7ErrorCode.UNSUPPORTED_MESSAGE_TYPE: "Unsupported message type",
    Hl7ErrorCode.UNSUPPORTED_EVENT_CODE: "Unsupported event code",
    Hl7ErrorCode.UNSUPPORTED_PROCESSING_ID: "Unsupported processing id",
    Hl7ErrorCode.UNSUPPORTED_VERSION_ID: "Unsupported version id",
    Hl7ErrorCode.DUPLICATE_KEY_IDENTIFIER: "Duplicate key identifier",
    Hl7ErrorCode.APPLICATION_INTERNAL_ERROR: "Application internal error",
}
