"""Pure aggregation helpers for the Agent Performance Dashboard (Week 4.2).

Four analytics primitives, one per chart in the dashboard:

  1. dispatches_by_channel_daily(session, company_id, days)
       → [{"day": "2026-04-20", "channel": "email", "count": 42}, ...]

  2. channel_funnel(session, company_id, days)
       → {"email": {"dispatched": 100, "delivered": 92, "replied": 18, "converted": 3}, ...}

  3. cost_by_stage(session, company_id, days)
       → [{"stage": "engaged", "cost_usd": 2.34, "leads": 15}, ...]

  4. latency_percentiles_by_task_type(session, company_id, days)
       → [{"task_type": "send_email", "p50_ms": 120, "p95_ms": 840, "count": 42}, ...]

All four are pure read functions; they don't write or mutate state. Good for
trivial unit tests + safe to call from multiple routes.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from models.models import AgentTask, EngagementEvent, Interaction, Lead, utc_now


# Helpers

def _window_start(days: int) -> Any:
    """Start of the rolling window, matching what the DB stores.

    SQLite returns naive datetimes from TIMESTAMP columns so we always compare
    naive-to-naive; Postgres with DateTime(timezone=True) preserves tzinfo.
    Strip tzinfo here for cross-dialect consistency in the analytics layer.
    """
    return (utc_now() - timedelta(days=days)).replace(tzinfo=None)


def _normalize_dt(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _day_key(dt) -> str:
    """YYYY-MM-DD string used as a consistent bucket label across dialects."""
    return dt.strftime("%Y-%m-%d")


# 1. Dispatches by channel (daily time series)

def dispatches_by_channel_daily(
    session: Session,
    company_id: int,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Outbound interaction counts bucketed per (day, channel).

    Draws from the Interaction table (the source of truth for "we sent this")
    rather than AgentTask. A task is only a *request* to send; Interactions
    are what actually went out. Matters for the dashboard to show real send
    volume, not queue depth.
    """
    start = _window_start(days)
    rows = session.exec(
        select(Interaction).where(
            Interaction.company_id == company_id,
            Interaction.direction == "outbound",
            Interaction.started_at >= start,
        )
    ).all()

    buckets: dict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        d = _normalize_dt(row.started_at)
        if d is None:
            continue
        buckets[(_day_key(d), row.channel or "unknown")] += 1

    return [
        {"day": day, "channel": channel, "count": count}
        for (day, channel), count in sorted(buckets.items())
    ]


# 2. Channel funnel

_CONVERSION_EVENTS = frozenset({"quote_accepted", "deal_won", "converted"})
_REPLY_EVENTS = frozenset({"replied", "whatsapp_inbound", "email_reply"})


def channel_funnel(
    session: Session,
    company_id: int,
    days: int = 30,
) -> dict[str, dict[str, int]]:
    """dispatched → delivered → replied → converted per channel.

    dispatched: count of outbound Interactions
    delivered:  subset with delivery_status in {sent, delivered, read}
    replied:    count of EngagementEvents of type in _REPLY_EVENTS
    converted:  count of EngagementEvents of type in _CONVERSION_EVENTS
    """
    start = _window_start(days)
    result: dict[str, dict[str, int]] = defaultdict(lambda: {
        "dispatched": 0, "delivered": 0, "replied": 0, "converted": 0,
    })

    # dispatched + delivered — from Interaction
    inter_rows = session.exec(
        select(Interaction).where(
            Interaction.company_id == company_id,
            Interaction.direction == "outbound",
            Interaction.started_at >= start,
        )
    ).all()
    for i in inter_rows:
        ch = i.channel or "unknown"
        result[ch]["dispatched"] += 1
        if i.delivery_status in ("sent", "delivered", "read"):
            result[ch]["delivered"] += 1

    # replied + converted — from EngagementEvent
    ee_rows = session.exec(
        select(EngagementEvent).where(
            EngagementEvent.company_id == company_id,
            EngagementEvent.created_at >= start,
        )
    ).all()
    for ee in ee_rows:
        ch = ee.channel or "unknown"
        if ee.event_type in _REPLY_EVENTS:
            result[ch]["replied"] += 1
        if ee.event_type in _CONVERSION_EVENTS:
            result[ch]["converted"] += 1

    return dict(result)


# 3. Cost per ISM stage

def cost_by_stage(
    session: Session,
    company_id: int,
    days: int = 7,
) -> list[dict[str, Any]]:
    """Aggregate AgentTask.output_json.metrics.cost_usd grouped by lead.ism_stage.

    A task is credited to whatever stage the LEAD is in when the task
    completes. Cheap + defensible: we care about "which stage is expensive
    to close", not "which action consumed tokens".
    """
    start = _window_start(days)
    rows = session.exec(
        select(AgentTask).where(
            AgentTask.company_id == company_id,
            AgentTask.status.in_(["done", "failed"]),
            AgentTask.completed_at >= start,
        )
    ).all()

    # Join lead info (stage) in Python — AgentTask doesn't have stage directly.
    # Cache leads per company to avoid N+1.
    lead_cache: dict[int, Lead | None] = {}

    def get_lead(lead_id):
        if lead_id is None:
            return None
        if lead_id not in lead_cache:
            lead_cache[lead_id] = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
            ).first()
        return lead_cache[lead_id]

    agg: dict[str, dict[str, Any]] = defaultdict(lambda: {"cost_usd": 0.0, "leads": set()})
    for task in rows:
        if task.lead_id is None:
            continue
        lead = get_lead(task.lead_id)
        stage = (lead.ism_stage if lead else None) or "unknown"

        output = task.output_json or {}
        metrics = output.get("metrics") or {}
        cost = float(metrics.get("cost_usd") or 0.0)
        agg[stage]["cost_usd"] += cost
        agg[stage]["leads"].add(task.lead_id)

    return [
        {"stage": stage, "cost_usd": round(data["cost_usd"], 4), "leads": len(data["leads"])}
        for stage, data in sorted(agg.items())
    ]


# 4. Latency percentiles per task_type

def _percentile(sorted_values: list[int], pct: float) -> int:
    """Simple nearest-rank percentile. Empty → 0."""
    if not sorted_values:
        return 0
    if pct <= 0:
        return sorted_values[0]
    if pct >= 100:
        return sorted_values[-1]
    # Index 0-based; pct/100 * (n-1) for interpolated, but use nearest-rank
    # for integer output — dashboard doesn't need sub-ms precision.
    k = int(round((pct / 100) * (len(sorted_values) - 1)))
    return sorted_values[k]


def latency_percentiles_by_task_type(
    session: Session,
    company_id: int,
    days: int = 7,
) -> list[dict[str, Any]]:
    """P50 + P95 + count per AgentTask.task_type.

    Reads AgentTask.output_json.metrics.latency_ms (populated by executors
    via services.agent.task_metrics). Tasks without metrics are skipped.
    """
    start = _window_start(days)
    rows = session.exec(
        select(AgentTask).where(
            AgentTask.company_id == company_id,
            AgentTask.status == "done",
            AgentTask.completed_at >= start,
        )
    ).all()

    by_type: dict[str, list[int]] = defaultdict(list)
    for task in rows:
        output = task.output_json or {}
        metrics = output.get("metrics") or {}
        latency = metrics.get("latency_ms")
        if latency is None:
            continue
        try:
            by_type[task.task_type].append(int(latency))
        except (TypeError, ValueError):
            continue

    result = []
    for task_type, values in sorted(by_type.items()):
        values.sort()
        result.append({
            "task_type": task_type,
            "p50_ms": _percentile(values, 50),
            "p95_ms": _percentile(values, 95),
            "count": len(values),
        })
    return result
