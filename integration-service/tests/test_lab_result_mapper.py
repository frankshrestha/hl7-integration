from hl7_integration.hl7.parser import ParsedMessage
from hl7_integration.mapping.lab_result_mapper import map_lab_result


def test_maps_sample_to_contract_json(parsed_lab_result_message: ParsedMessage) -> None:
    assert map_lab_result(parsed_lab_result_message).model_dump(mode="json") == {
        "message_id": "MSG00001",
        "message_type": "ORU^R01",
        "message_datetime": "2026-10-01T10:30:00",
        "patient": {
            "external_id": "PAT00001",
            "first_name": "JOHN",
            "last_name": "DOE",
            "dob": "1990-01-01",
            "gender": "M",
        },
        "order": {
            "order_no": "ORD00001",
            "service_code": "CBC",
            "service_name": "Complete Blood Count",
        },
        "results": [
            {
                "set_id": 1,
                "code": "HB",
                "name": "Hemoglobin",
                "value": "13.5",
                "value_type": "NM",
                "unit": "g/dL",
                "reference_range": "12-16",
                "flag": "N",
                "result_status": "F",
                "observed_at": None,
            },
            {
                "set_id": 2,
                "code": "WBC",
                "name": "White Blood Cell Count",
                "value": "7500",
                "value_type": "NM",
                "unit": "cells/uL",
                "reference_range": "4000-11000",
                "flag": "N",
                "result_status": "F",
                "observed_at": None,
            },
        ],
    }
