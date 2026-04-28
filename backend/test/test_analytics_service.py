"""Tests for Week 4.2a — analytics_service aggregation helpers.

Each helper is tested in isolation with seeded data. Uses in-memory sqlite,
same pattern as the Week 1-3 invariant suites.

Invariants:
  1. dispatches_by_channel_daily buckets per (day, channel) correctly
  2. channel_funnel respects the delivery_status → delivered mapping and
     the _CONVERSION_EVENTS + _REPLY_EVENTS sets
  3. cost_by_stage sums AgentTask.output_json.metrics.cost_usd per lead stage
  4. latency_percentiles_by_task_type returns p50/p95/count per task_type
  5. All helpers respect the `days` window and skip older rows
  6. Missing metrics fields fail gracefully (don't error)
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import (
    AgentTask, EngagementEvent, Interaction, Lead, utc_now,
)
from services.agent.analytics_service import (
    channel_funnel,
    cost_by_stage,
    dispatches_by_channel_daily,
    latency_percentiles_by_task_type,
)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def _seed_lead(session, **overrides):
    defaults = {
        "company_id": 1, "name": "Test", "normalized_phone": "+1",
        "email": "x@y.z", "ism_stage": "engaged",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


def _seed_interaction(session, lead_id=None, days_ago=0, channel="email",
                      direction="outbound", delivery_status="sent"):
    inter = Interaction(
        company_id=1, lead_id=lead_id,
        type="communication", channel=channel, direction=direction,
        delivery_status=delivery_status,
        started_at=utc_now() - timedelta(days=days_ago),
    )
    session.add(inter); session.commit(); session.refresh(inter)
    return inter


def _seed_engagement(session, event_type="replied", channel="email", days_ago=0):
    ee = EngagementEvent(
        company_id=1, channel=channel, event_type=event_type,
        created_at=utc_now() - timedelta(days=days_ago),
    )
    session.add(ee); session.commit(); session.refresh(ee)
    return ee


def _seed_task(session, lead_id=None, task_type="send_email",
               days_ago=0, cost_usd=0.01, latency_ms=100, status="done"):
    task = AgentTask(
        company_id=1, lead_id=lead_id, task_type=task_type,
        assigned_agent="send", status=status,
        input_json={"task_type": task_type},
        output_json={"metrics": {"cost_usd": cost_usd, "latency_ms": latency_ms}},
        completed_at=utc_now() - timedelta(days=days_ago),
    )
    session.add(task); session.commit(); session.refresh(task)
    return task


# dispatches_by_channel_daily

class TestDispatchesByChannelDaily:
    def test_empty_db_returns_empty_list(self, session):
        assert dispatches_by_channel_daily(session, 1) == []

    def test_buckets_per_day_channel(self, session):
        _seed_interaction(session, days_ago=0, channel="email")
        _seed_interaction(session, days_ago=0, channel="email")
        _seed_interaction(session, days_ago=0, channel="whatsapp")
        _seed_interaction(session, days_ago=1, channel="email")

        result = dispatches_by_channel_daily(session, 1, days=30)
        # Sort by (day, channel)
        counts = {(r["day"], r["channel"]): r["count"] for r in result}
        today = (utc_now()).strftime("%Y-%m-%d")
        yesterday = (utc_now() - timedelta(days=1)).strftime("%Y-%m-%d")
        assert counts[(today, "email")] == 2
        assert counts[(today, "whatsapp")] == 1
        assert counts[(yesterday, "email")] == 1

    def test_respects_days_window(self, session):
        _seed_interaction(session, days_ago=0, channel="email")
        _seed_interaction(session, days_ago=40, channel="email")
        result = dispatches_by_channel_daily(session, 1, days=30)
        assert sum(r["count"] for r in result) == 1  # 40-day-old filtered out

    def test_ignores_inbound(self, session):
        _seed_interaction(session, direction="inbound", channel="whatsapp")
        _seed_interaction(session, direction="outbound", channel="whatsapp")
        result = dispatches_by_channel_daily(session, 1)
        assert sum(r["count"] for r in result) == 1


# channel_funnel

class TestChannelFunnel:
    def test_empty_funnel(self, session):
        assert channel_funnel(session, 1) == {}

    def test_dispatched_and_delivered_from_interactions(self, session):
        _seed_interaction(session, channel="email", delivery_status="sent")
        _seed_interaction(session, channel="email", delivery_status="delivered")
        _seed_interaction(session, channel="email", delivery_status="failed")

        funnel = channel_funnel(session, 1)
        assert funnel["email"]["dispatched"] == 3
        assert funnel["email"]["delivered"] == 2  # sent + delivered
        assert funnel["email"]["replied"] == 0

    def test_replied_and_converted_from_engagement_events(self, session):
        _seed_interaction(session, channel="email")
        _seed_engagement(session, event_type="replied", channel="email")
        _seed_engagement(session, event_type="quote_accepted", channel="email")
        _seed_engagement(session, event_type="some_other_event", channel="email")  # not counted

        funnel = channel_funnel(session, 1)
        assert funnel["email"]["replied"] == 1
        assert funnel["email"]["converted"] == 1

    def test_unknown_channel_falls_to_unknown_bucket(self, session):
        _seed_interaction(session, channel=None)  # no channel
        funnel = channel_funnel(session, 1)
        assert "unknown" in funnel


# cost_by_stage

class TestCostByStage:
    def test_sums_cost_per_lead_stage(self, session):
        l1 = _seed_lead(session, ism_stage="engaged", normalized_phone="+1001")
        l2 = _seed_lead(session, ism_stage="negotiation", normalized_phone="+1002")

        _seed_task(session, lead_id=l1.id, cost_usd=0.10)
        _seed_task(session, lead_id=l1.id, cost_usd=0.20)
        _seed_task(session, lead_id=l2.id, cost_usd=0.05)

        result = cost_by_stage(session, 1, days=7)
        rows = {r["stage"]: r for r in result}
        assert rows["engaged"]["cost_usd"] == 0.30
        assert rows["engaged"]["leads"] == 1  # same lead, two tasks → 1 lead
        assert rows["negotiation"]["cost_usd"] == 0.05
        assert rows["negotiation"]["leads"] == 1

    def test_missing_metrics_treated_as_zero(self, session):
        lead = _seed_lead(session, ism_stage="engaged")
        task = AgentTask(
            company_id=1, lead_id=lead.id, task_type="send_email",
            assigned_agent="send", status="done",
            input_json={}, output_json={},  # no metrics key
            completed_at=utc_now(),
        )
        session.add(task); session.commit()

        result = cost_by_stage(session, 1)
        assert result == [{"stage": "engaged", "cost_usd": 0.0, "leads": 1}]

    def test_ignores_pending_tasks(self, session):
        """Cost is credited only when the task actually completes."""
        lead = _seed_lead(session, ism_stage="engaged")
        _seed_task(session, lead_id=lead.id, cost_usd=0.50, status="pending")
        assert cost_by_stage(session, 1) == []


# latency_percentiles_by_task_type

class TestLatencyPercentiles:
    def test_empty_returns_empty(self, session):
        assert latency_percentiles_by_task_type(session, 1) == []

    def test_single_task_p50_and_p95_are_that_value(self, session):
        _seed_task(session, task_type="send_email", latency_ms=100)
        result = latency_percentiles_by_task_type(session, 1)
        assert result[0]["task_type"] == "send_email"
        assert result[0]["p50_ms"] == 100
        assert result[0]["p95_ms"] == 100
        assert result[0]["count"] == 1

    def test_percentiles_scale_correctly(self, session):
        # 20 tasks: latencies 10, 20, 30, ..., 200
        for i in range(1, 21):
            _seed_task(session, task_type="send_whatsapp", latency_ms=i * 10)

        result = latency_percentiles_by_task_type(session, 1)
        wa = next(r for r in result if r["task_type"] == "send_whatsapp")
        assert wa["count"] == 20
        # p50 of 20 values (1-based) = ~10th or 11th value = 100 or 110
        assert 90 <= wa["p50_ms"] <= 120
        # p95 = ~19th value = 190
        assert 180 <= wa["p95_ms"] <= 200

    def test_missing_latency_field_skipped(self, session):
        task = AgentTask(
            company_id=1, lead_id=1, task_type="send_email",
            assigned_agent="send", status="done",
            input_json={}, output_json={"metrics": {}},  # no latency_ms
            completed_at=utc_now(),
        )
        session.add(task); session.commit()
        assert latency_percentiles_by_task_type(session, 1) == []

    def test_groups_by_task_type(self, session):
        _seed_task(session, task_type="send_email", latency_ms=50)
        _seed_task(session, task_type="send_whatsapp", latency_ms=200)
        _seed_task(session, task_type="send_email", latency_ms=100)

        result = latency_percentiles_by_task_type(session, 1)
        types = {r["task_type"]: r for r in result}
        assert types["send_email"]["count"] == 2
        assert types["send_whatsapp"]["count"] == 1
