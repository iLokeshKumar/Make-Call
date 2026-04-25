"""Observability primitives — counters, gauges, trace helpers.

Kept dependency-free so /health and tests can import them without dragging
the LLM-provider chain (groq/anthropic/google/cerebras/openai SDKs).
"""
from .rate_limit_metrics import (  # noqa: F401
    get_rate_limit_hits_last_15min,
    record_rate_limit_hit,
)
from .request_metrics import (  # noqa: F401
    get_availability_snapshot,
    record_response,
)
