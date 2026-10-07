import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
from pydantic import ValidationError

from hl7_integration.forwarding.hmac_signer import CLIENT_ID_HEADER, SIGNATURE_HEADER, sign_request
from hl7_integration.models.lab_result import LabResultPayload

CORRELATION_ID_HEADER = "X-Correlation-ID"
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429})


@dataclass(frozen=True)
class ForwardingOutcome:
    """Result of delivery attempt."""

    is_delivered: bool
    is_retryable: bool
    http_status: int | None
    error_message: str | None = None
    response_excerpt: str | None = None

    @property
    def is_permanent_failure(self) -> bool:
        return not self.is_delivered and not self.is_retryable


class LabResultApiClient:
    def __init__(
        self,
        api_url: str,
        client_id: str,
        hmac_secret: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_url = api_url
        self._client_id = client_id
        self._hmac_secret = hmac_secret
        self._http_client = httpx.AsyncClient(timeout=timeout_seconds, transport=transport)

    async def close(self) -> None:
        await self._http_client.aclose()

    def build_request_body(self, normalized_payload: dict[str, Any]) -> bytes:
        contract_payload = LabResultPayload.model_validate(normalized_payload)
        request_document = contract_payload.model_dump(mode="json")
        return json.dumps(request_document, separators=(",", ":"), ensure_ascii=False).encode()

    async def send_lab_result(
        self, normalized_payload: dict[str, Any], correlation_id: UUID
    ) -> ForwardingOutcome:
        try:
            request_body = self.build_request_body(normalized_payload)
        except ValidationError as contract_error:
            return ForwardingOutcome(
                is_delivered=False,
                is_retryable=False,
                http_status=None,
                error_message=f"Stored payload does not match the API contract: {contract_error}",
            )
        request = self._http_client.build_request(
            "POST",
            self._api_url,
            content=request_body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                CORRELATION_ID_HEADER: str(correlation_id),
                CLIENT_ID_HEADER: self._client_id,
            },
        )

        request.headers[SIGNATURE_HEADER] = sign_request(
            self._hmac_secret, request.method, request.url.raw_path.decode("ascii"), request_body
        )
        try:
            response = await self._http_client.send(request)
        except httpx.TimeoutException as timeout_error:
            return ForwardingOutcome(
                is_delivered=False,
                is_retryable=True,
                http_status=None,
                error_message=f"Timeout calling lab results API: {timeout_error!r}",
            )
        except httpx.TransportError as transport_error:
            return ForwardingOutcome(
                is_delivered=False,
                is_retryable=True,
                http_status=None,
                error_message=f"Lab results API unreachable: {transport_error!r}",
            )
        return classify_response(response.status_code, response.text[:500])


def classify_response(status_code: int, response_excerpt: str) -> ForwardingOutcome:
    """2xx = stored, timeouts/429/5xx = try again, other 4xx (incl. 409) = retrying cannot help."""
    if 200 <= status_code < 300:
        return ForwardingOutcome(
            is_delivered=True,
            is_retryable=False,
            http_status=status_code,
            response_excerpt=response_excerpt,
        )
    is_retryable = status_code >= 500 or status_code in RETRYABLE_STATUS_CODES
    return ForwardingOutcome(
        is_delivered=False,
        is_retryable=is_retryable,
        http_status=status_code,
        error_message=f"Lab results API responded with HTTP {status_code}",
        response_excerpt=response_excerpt,
    )
