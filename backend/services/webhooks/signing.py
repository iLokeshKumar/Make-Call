import hashlib
import hmac
import time

def _build_signature(secret: str, payload: bytes, timestamp: str | None = None) -> str:
    ts = timestamp or str(int(time.time()))
    signed_payload = f"{ts}.{payload.decode()}"
    sig = hmac.new(secret.encode(), signed_payload.encode(), hashlib.sha256).hexdigest()
    return f"v1={sig}"

def _verify_signature(secret: str, payload: bytes, signature_header: str) -> bool:
    try:
        received = signature_header.split("=", 1)[1]
        expected = _build_signature(secret, payload)
        return hmac.compare_digest(received, expected)
    except (IndexError, ValueError):
        return False