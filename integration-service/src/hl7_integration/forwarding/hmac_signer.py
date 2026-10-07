import hashlib
import hmac

CLIENT_ID_HEADER = "X-Client-Id"
SIGNATURE_HEADER = "X-Signature"


def sign_request(shared_secret: str, method: str, request_uri: str, request_body: bytes) -> str:
    body_hash = hashlib.sha256(request_body).hexdigest()
    canonical_request = f"{method.upper()}\n{request_uri}\n{body_hash}"
    return hmac.new(shared_secret.encode(), canonical_request.encode(), hashlib.sha256).hexdigest()


def is_valid_signature(
    shared_secret: str,
    method: str,
    request_uri: str,
    request_body: bytes,
    provided_signature: str,
) -> bool:
    expected_signature = sign_request(shared_secret, method, request_uri, request_body)
    return hmac.compare_digest(expected_signature, provided_signature)
