"""In-process HTTP request counter for SLO #1 (API availability).

Counters are process-local and reset on restart.  Window claims in
`docs/SLOs.md` say "since last restart" until persistent storage lands.
"""
from __future__ import annotations

import time
from threading import Lock

_lock = Lock()
_total_requests = 0
_5xx_responses = 0
_started_at = time.monotonic()


def record_response(method: str, status: int) -> None:
    global _total_requests, _5xx_responses
    if (method or "").upper() == "OPTIONS":
        return
    with _lock:
        _total_requests += 1
        if status >= 500:
            _5xx_responses += 1


def get_availability_snapshot() -> dict:
    with _lock:
        total = _total_requests
        five = _5xx_responses
        uptime = time.monotonic() - _started_at
    if total == 0:
        return {"total": 0, "five_xx": 0, "availability": None, "uptime_seconds": uptime}
    return {
        "total": total,
        "five_xx": five,
        "availability": (total - five) / total,
        "uptime_seconds": uptime,
    }


def _reset_for_tests() -> None:
    global _total_requests, _5xx_responses, _started_at
    with _lock:
        _total_requests = 0
        _5xx_responses = 0
        _started_at = time.monotonic()
