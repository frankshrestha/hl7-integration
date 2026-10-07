from pydantic import BaseModel


class Patient(BaseModel):
    external_id: str
    first_name: str
    last_name: str
    dob: str | None
    gender: str | None


class Order(BaseModel):
    order_no: str
    service_code: str
    service_name: str


class ObservationResult(BaseModel):
    set_id: int | None = None
    code: str
    name: str
    value: str
    value_type: str | None = None
    unit: str
    reference_range: str
    flag: str
    result_status: str | None = None
    observed_at: str | None = None


class LabResultPayload(BaseModel):
    message_id: str
    message_type: str | None = None
    message_datetime: str
    patient: Patient
    order: Order
    results: list[ObservationResult]
