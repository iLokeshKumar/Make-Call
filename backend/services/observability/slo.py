"""SLO evaluation — pure functions over DB + in-memory counters.

Returns a list of dicts shaped for the /admin/slo-status endpoint:

    {
      "id": "voice_p95_ms",
      "target": 800,
      "actual": 1420,
      "status": "breach" | "at_risk" | "ok" | "insufficient_data",
      "window": "7d",
      "samples": 142,
      "unit": "ms" | "ratio",
      "direction": "lower_is_better" | "higher_is_better",
    }

`status` rules:
  * samples < MIN_SAMPLES (10) → insufficient_data (don't false-alarm).
  * lower_is_better:  actual > target            → breach
                      actual within [80%, 100%] of target → at_risk
                      otherwise                  → ok
  * higher_is_better: actual < target            → breach
                      actual within [target, 110%] (above target by ≤10%) → at_risk
                      otherwise                  → ok
"""
from __future__ import annotations

import statistics
from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from models.models import AgentTask, LatencyLog, UiLatencyLog, utc_now
from services.observability import get_availability_snapshot

MIN_SAMPLES = 10


def _percentile(values: list[float], pct: int) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return float(values[0])
    quantiles = statistics.quantiles(values, n=100, method="inclusive")
    return float(quantiles[max(0, min(98, pct - 1))])


def _classify_lower_is_better(actual: float, target: float) -> str:
    if actual > target:
        return "breach"
    if actual >= target * 0.8:
        return "at_risk"
    return "ok"


def _classify_higher_is_better(actual: float, target: float) -> str:
    if actual < target:
        return "breach"
    # No "at_risk" zone for ratio metrics — either you hit it or you don't.
    return "ok"


def _slo_api_availability() -> dict[str, Any]:
    snap = get_availability_snapshot()
    samples = snap["total"]
    target = 0.995
    base = {
        "id": "api_availability",
        "target": target,
        "window": "since_restart",
        "samples": samples,
        "unit": "ratio",
        "direction": "higher_is_better",
    }
    if samples < MIN_SAMPLES:
        return {**base, "actual": None, "status": "insufficient_data"}
    actual = snap["availability"] or 0.0
    return {**base, "actual": actual, "status": _classify_higher_is_better(actual, target)}


def _slo_voice_p95(session: Session, company_id: int | None) -> dict[str, Any]:
    cutoff = utc_now() - timedelta(days=7)
    query = select(LatencyLog).where(LatencyLog.created_at >= cutoff)
    if company_id is not None:
        query = query.where(LatencyLog.company_id == company_id)
    rows = session.exec(query).all()
    durations = [float(r.total_ms) for r in rows if r.total_ms is not None]
    target = 800.0
    base = {
        "id": "voice_p95_ms",
        "target": target,
        "window": "7d",
        "samples": len(durations),
        "unit": "ms",
        "direction": "lower_is_better",
    }
    if len(durations) < MIN_SAMPLES:
        return {**base, "actual": None, "status": "insufficient_data"}
    p95 = _percentile(durations, 95)
    return {**base, "actual": p95, "status": _classify_lower_is_better(p95, target)}


def _slo_login_dashboard_p95(session: Session, company_id: int | None) -> dict[str, Any]:
    cutoff = utc_now() - timedelta(days=7)
    query = select(UiLatencyLog).where(
        UiLatencyLog.created_at >= cutoff,
        UiLatencyLog.event == "fmp",
        UiLatencyLog.route == "/",
    )
    if company_id is not None:
        query = query.where(UiLatencyLog.company_id == company_id)
    rows = session.exec(query).all()
    durations = [float(r.duration_ms) for r in rows]
    target = 2000.0
    base = {
        "id": "login_dashboard_p95_ms",
        "target": target,
        "window": "7d",
        "samples": len(durations),
        "unit": "ms",
        "direction": "lower_is_better",
    }
    if len(durations) < MIN_SAMPLES:
        return {**base, "actual": None, "status": "insufficient_data"}
    p95 = _percentile(durations, 95)
    return {**base, "actual": p95, "status": _classify_lower_is_better(p95, target)}


def _slo_dead_letter_rate(session: Session, company_id: int | None) -> dict[str, Any]:
    cutoff = utc_now() - timedelta(days=7)
    query = select(AgentTask).where(AgentTask.created_at >= cutoff)
    if company_id is not None:
        query = query.where(AgentTask.company_id == company_id)
    rows = session.exec(query).all()
    total = len(rows)
    target = 0.005  # 0.5% — lower is better
    base = {
        "id": "agent_task_dead_letter_rate",
        "target": target,
        "window": "7d",
        "samples": total,
        "unit": "ratio",
        "direction": "lower_is_better",
    }
    if total < MIN_SAMPLES:
        return {**base, "actual": None, "status": "insufficient_data"}
    # For AgentTask, 'failed' is the terminal failure state (dead letter)
    dead = sum(1 for r in rows if (r.status or "").lower() == "failed")
    actual = dead / total
    return {**base, "actual": actual, "status": _classify_lower_is_better(actual, target)}


def evaluate_all(session: Session, company_id: int | None = None) -> list[dict[str, Any]]:
    return [
        _slo_api_availability(),
        _slo_login_dashboard_p95(session, company_id),
        _slo_voice_p95(session, company_id),
        _slo_dead_letter_rate(session, company_id),
    ]
