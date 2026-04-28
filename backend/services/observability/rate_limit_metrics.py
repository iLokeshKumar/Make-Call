"""Provider-agnostic rate-limit hit counter.

Lives outside any provider module so observability tests + /health can
import it without dragging the full LLM-provider chain (groq, anthropic,
google, cerebras, openai SDKs).

Sliding window: 15 minutes.  Process-local; not shared across workers.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock

_RATE_LIMIT_WINDOW_SECONDS = 15 * 60
_rate_limit_hits: deque[float] = deque()
_rate_limit_lock = Lock()


def record_rate_limit_hit() -> None:
    now = time.monotonic()
    with _rate_limit_lock:
        _rate_limit_hits.append(now)
        cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
        while _rate_limit_hits and _rate_limit_hits[0] < cutoff:
            _rate_limit_hits.popleft()


def get_rate_limit_hits_last_15min() -> int:
    now = time.monotonic()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    with _rate_limit_lock:
        while _rate_limit_hits and _rate_limit_hits[0] < cutoff:
            _rate_limit_hits.popleft()
        return len(_rate_limit_hits)


def _reset_for_tests() -> None:
    with _rate_limit_lock:
        _rate_limit_hits.clear()
