import re
from dataclasses import dataclass

from hl7apy.consts import VALIDATION_LEVEL
from hl7apy.core import Element, Message, Segment
from hl7apy.exceptions import HL7apyException, UnsupportedVersion
from hl7apy.parser import parse_message as parse_hl7apy_message

from hl7_integration.hl7.error_codes import Hl7ErrorCode
from hl7_integration.hl7.escaping import unescape_value

type ParsedMessage = Message

SEGMENT_TERMINATOR_PATTERN = re.compile(r"\r\n|\r|\n")


class Hl7ParseError(ValueError):
    def __init__(self, message: str, error_code: Hl7ErrorCode) -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class MessageHeader:
    sending_application: str
    sending_facility: str
    receiving_application: str
    receiving_facility: str
    message_date_time: str
    message_type: str
    trigger_event: str
    message_control_id: str
    processing_id: str
    version_id: str


def parse_message(raw_message: str) -> ParsedMessage:
    """Parse a raw HL7 v2 message. Requires the message to start with an MSH segment."""
    segment_lines = [
        line
        for line in SEGMENT_TERMINATOR_PATTERN.split(raw_message.strip().lstrip("﻿"))
        if line.strip()
    ]
    if not segment_lines or not segment_lines[0].startswith("MSH"):
        raise Hl7ParseError(
            "Message must start with an MSH segment", Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR
        )
    try:
        return parse_hl7apy_message(
            "\r".join(segment_lines),
            validation_level=VALIDATION_LEVEL.TOLERANT,
            find_groups=False,
        )
    except UnsupportedVersion as version_error:
        error_code = (
            Hl7ErrorCode.UNSUPPORTED_VERSION_ID
            if _declared_version(segment_lines[0])
            else Hl7ErrorCode.REQUIRED_FIELD_MISSING
        )
        raise Hl7ParseError(str(version_error), error_code) from version_error
    except HL7apyException as hl7apy_error:
        raise Hl7ParseError(
            f"Message could not be parsed: {hl7apy_error}", Hl7ErrorCode.SEGMENT_SEQUENCE_ERROR
        ) from hl7apy_error


def parse_grouped_message(message: ParsedMessage) -> Message:
    return parse_hl7apy_message(
        message.to_er7(), validation_level=VALIDATION_LEVEL.TOLERANT, find_groups=True
    )


def find_segments(message: ParsedMessage, segment_id: str) -> list[Segment]:
    return [segment for segment in message.children if segment.name == segment_id]


def find_first_segment(message: ParsedMessage, segment_id: str) -> Segment | None:
    matching_segments = find_segments(message, segment_id)
    return matching_segments[0] if matching_segments else None


def read_value(element: Element) -> str:
    return unescape_value(element.value or "", element.encoding_chars)


def read_component(field: Element, component_position: int) -> str:
    for component in field.children:
        if component.name.rsplit("_", 1)[-1] == str(component_position):
            return read_value(component)
    components = (field.value or "").split(field.encoding_chars["COMPONENT"])
    if component_position > len(components):
        return ""
    return unescape_value(components[component_position - 1], field.encoding_chars)


def read_header(message: ParsedMessage) -> MessageHeader:
    header = message.msh
    return MessageHeader(
        sending_application=read_component(header.msh_3, 1),
        sending_facility=read_component(header.msh_4, 1),
        receiving_application=read_component(header.msh_5, 1),
        receiving_facility=read_component(header.msh_6, 1),
        message_date_time=read_component(header.msh_7, 1),
        message_type=read_component(header.msh_9, 1),
        trigger_event=read_component(header.msh_9, 2),
        message_control_id=read_value(header.msh_10),
        processing_id=read_component(header.msh_11, 1),
        version_id=read_component(header.msh_12, 1),
    )


def try_parse_message(raw_message: str) -> ParsedMessage | None:
    try:
        return parse_message(raw_message)
    except Hl7ParseError:
        return None


def _declared_version(header_line: str) -> str:
    field_separator = header_line[3:4] or "|"
    header_fields = header_line.split(field_separator)
    return header_fields[11].strip() if len(header_fields) > 11 else ""
