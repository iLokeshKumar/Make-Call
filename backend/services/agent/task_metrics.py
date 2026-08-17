"""Task metrics helper — record LLM usage + latency on AgentTask.output_json.

Every executor that calls an LLM or does meaningful work should record
usage metrics so the Week 4 Performance Dashboard has something to chart.
This module standardises the field names so charts don't have to handle
per-agent variations.

Canonical fields written into `output_json` under the `metrics` key:

    metrics: {
        "tokens_in":     int,       # prompt tokens
        "tokens_out":    int,       # completion tokens
        "tokens_total":  int,       # sum (redundant but cheap + useful)
        "cost_usd":      float,     # estimated dollar cost
        "latency_ms":    int,       # end-to-end time for this task execution
        "llm_provider":  str | None,
        "llm_model":     str | None,
    }

The send executor + webhook_sink don't call LLMs, so they only record
`latency_ms`. LLM-using agents (post_call, researcher, coach, etc.) record
the full set — wiring those is out of Week 4 scope.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Iterator, Optional


# Very rough per-provider cost tables (USD per 1K tokens). Accurate enough
# for a dashboard; exact billing lives with the provider. Update when
# pricing changes — tests don't depend on the specific numbers.
_PRICE_PER_1K_TOKENS: dict[str, tuple[float, float]] = {
    # provider/model : (input_per_1k, output_per_1k)
    "openai/gpt-4o":              (0.0025, 0.010),
    "openai/gpt-4o-mini":         (0.00015, 0.0006),
    "anthropic/claude-opus-4-7":  (0.015, 0.075),
    "anthropic/claude-sonnet-4-6": (0.003, 0.015),
    "anthropic/claude-haiku-4-5": (0.0008, 0.004),
    "gemini/gemini-2.0-flash":    (0.000075, 0.0003),
    "mistral/mistral-large":      (0.002, 0.006),
}


def estimate_cost_usd(
    tokens_in: int,
    tokens_out: int,
    provider: Optional[str],
    model: Optional[str],
) -> float:
    """Rough USD cost estimate. Returns 0.0 if provider/model unknown."""
    if not provider or not model:
        return 0.0
    key = f"{provider}/{model}"
    price = _PRICE_PER_1K_TOKENS.get(key)
    if price is None:
        return 0.0
    in_price, out_price = price
    return (tokens_in / 1000) * in_price + (tokens_out / 1000) * out_price


def build_metrics(
    *,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
    llm_provider: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> dict[str, Any]:
    """Return the canonical metrics dict for output_json['metrics']."""
    return {
        "tokens_in": int(tokens_in),
        "tokens_out": int(tokens_out),
        "tokens_total": int(tokens_in + tokens_out),
        "cost_usd": round(
            estimate_cost_usd(tokens_in, tokens_out, llm_provider, llm_model),
            6,
        ),
        "latency_ms": int(latency_ms),
        "llm_provider": llm_provider,
        "llm_model": llm_model,
    }


@contextmanager
def time_block() -> Iterator[dict[str, int]]:
    """Context manager that measures elapsed wall-time in milliseconds.

    Usage:
        with time_block() as t:
            ...
        print(t["ms"])
    """
    result = {"ms": 0}
    start = time.perf_counter()
    try:
        yield result
    finally:
        result["ms"] = int((time.perf_counter() - start) * 1000)


def merge_metrics_into_output(
    output: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    """Add `metrics` under `output["metrics"]`, preserving existing output keys.

    Mutates in place AND returns the dict for convenience.
    """
    output["metrics"] = metrics
    return output
