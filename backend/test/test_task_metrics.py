"""Tests for Week 4.3 — task metrics helper.

Invariants:
  1. build_metrics returns the canonical field set with correct types
  2. estimate_cost_usd returns 0 for unknown provider/model
  3. estimate_cost_usd scales linearly with token counts
  4. time_block measures at least ~0ms (monotonic, non-negative)
  5. merge_metrics_into_output puts metrics under 'metrics' key and preserves
     existing keys
  6. Send executor populates `output["metrics"]` with latency_ms on every call
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import time

import pytest

from services.agent.task_metrics import (
    build_metrics,
    estimate_cost_usd,
    merge_metrics_into_output,
    time_block,
)


class TestBuildMetrics:
    def test_returns_canonical_shape(self):
        m = build_metrics(tokens_in=100, tokens_out=50, latency_ms=234,
                          llm_provider="openai", llm_model="gpt-4o-mini")
        assert set(m.keys()) == {
            "tokens_in", "tokens_out", "tokens_total",
            "cost_usd", "latency_ms", "llm_provider", "llm_model",
        }
        assert m["tokens_in"] == 100
        assert m["tokens_out"] == 50
        assert m["tokens_total"] == 150
        assert m["latency_ms"] == 234
        assert m["llm_provider"] == "openai"
        assert m["llm_model"] == "gpt-4o-mini"
        assert isinstance(m["cost_usd"], float)
        assert m["cost_usd"] >= 0

    def test_zero_tokens_zero_cost(self):
        m = build_metrics(tokens_in=0, tokens_out=0, latency_ms=5)
        assert m["cost_usd"] == 0.0
        assert m["tokens_total"] == 0


class TestEstimateCost:
    def test_known_provider_model_scales_linearly(self):
        # Gpt-4o-mini: $0.00015/1K input, $0.0006/1K output
        cost_1k = estimate_cost_usd(1000, 1000, "openai", "gpt-4o-mini")
        cost_2k = estimate_cost_usd(2000, 2000, "openai", "gpt-4o-mini")
        # Allow float tolerance
        assert abs(cost_2k - 2 * cost_1k) < 1e-9

    def test_unknown_provider_returns_zero(self):
        assert estimate_cost_usd(1000, 1000, "unknown-provider", "some-model") == 0.0

    def test_missing_provider_returns_zero(self):
        assert estimate_cost_usd(1000, 1000, None, "gpt-4o") == 0.0
        assert estimate_cost_usd(1000, 1000, "openai", None) == 0.0


class TestTimeBlock:
    def test_measures_elapsed_time(self):
        with time_block() as t:
            time.sleep(0.01)  # 10ms
        assert t["ms"] >= 5  # generous lower bound for test flakiness

    def test_zero_work_measures_tiny_but_nonnegative(self):
        with time_block() as t:
            pass
        assert t["ms"] >= 0


class TestMergeMetrics:
    def test_adds_metrics_key_without_clobbering_output(self):
        output = {"ok": True, "channel": "email", "result": {"sent": True}}
        metrics = build_metrics(latency_ms=42)
        merged = merge_metrics_into_output(output, metrics)

        assert merged["ok"] is True
        assert merged["channel"] == "email"
        assert merged["result"] == {"sent": True}
        assert merged["metrics"]["latency_ms"] == 42

    def test_mutates_in_place_and_returns(self):
        output = {"ok": True}
        merge_metrics_into_output(output, build_metrics(latency_ms=1))
        assert "metrics" in output


# Integration: send executor emits metrics

class TestSendExecutorEmitsMetrics:
    @pytest.mark.asyncio
    async def test_unknown_task_still_emits_metrics(self):
        """Even on error paths the executor should record latency so the
        Performance dashboard doesn't have gaps on failure."""
        from agents.send import run
        result = await run(company_id=1, actor_user_id=0, lead_id=1, task_type="bogus")
        assert result["ok"] is False
        assert "metrics" in result
        assert result["metrics"]["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_missing_task_type_still_emits_metrics(self):
        from agents.send import run
        result = await run(company_id=1, actor_user_id=0, lead_id=1)
        assert "metrics" in result
