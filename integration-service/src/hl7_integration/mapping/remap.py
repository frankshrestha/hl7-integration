from typing import Any

from hl7_integration.hl7.parser import Hl7ParseError, parse_message
from hl7_integration.mapping.lab_result_mapper import LabResultMappingError, map_lab_result


class RemapError(Exception):
    pass


def remap_stored_message(raw_payload: str) -> dict[str, Any]:
    try:
        return map_lab_result(parse_message(raw_payload)).model_dump(mode="json")
    except (Hl7ParseError, LabResultMappingError) as mapping_error:
        raise RemapError(str(mapping_error)) from mapping_error
