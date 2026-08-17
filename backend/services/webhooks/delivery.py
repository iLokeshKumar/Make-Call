import asyncio
import hashlib
import hmac
import json
import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

def _build_headers(secret: str | None, payload: bytes | str) -> dict[str, str]:
    if isinstance(payload, str):
        payload_bytes = payload.encode()
    else:
        payload_bytes = payload
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "RioCRM-Webhook/1.0",
        "X-RioCRM-Event": "",    # filled in by caller
        "X-RioCRM-Delivery": __import__('secrets').token_hex(8),
    }
    if secret:
        ts = str(int(time.time()))
        signed = hmac.new(secret.encode(), f"{ts}.{payload_bytes.decode()}".encode(), hashlib.sha256).hexdigest()
        headers["X-RioCRM-Timestamp"] = ts
        headers["X-RioCRM-Signature"] = f"v1={signed}"
    return headers

async def deliver(webhook_url: str, event_type: str, payload: dict[str, Any],
                  secret: str | None = None, timeout: float = 10.0) -> dict:
    body = json.dumps(payload, default=str)
    headers = _build_headers(secret, body)
    headers["X-RioCRM-Event"] = event_type
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, content=body, headers=headers)
        ms = int((time.monotonic() - t0) * 1000)
        return {"ok": resp.status_code < 400, "http_status": resp.status_code,
                "response_ms": ms, "error": None}
    except Exception as exc:
        ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "http_status": None, "response_ms": ms, "error": str(exc)[:500]}