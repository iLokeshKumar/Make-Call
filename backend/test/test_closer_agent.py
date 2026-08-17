"""Tests for Week 7.3 — Closer agent + silence-scan worker helper."""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from decimal import Decimal

from models.models import (
    AgentTask,
    CompetitorMention,
    Interaction,
    Lead,
    ObjectionEntry,
    Quote,
)


# Stubs
_stub_call = types.ModuleType("call")
_stub_call_outbound = types.ModuleType("call.outbound_call_service")
_stub_call_outbound.create_call_task = lambda **kw: types.SimpleNamespace(id=0)
_stub_call.outbound_call_service = _stub_call_outbound
sys.modules.setdefault("call", _stub_call)
sys.modules.setdefault("call.outbound_call_service", _stub_call_outbound)


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
def session(engine, monkeypatch):
    # Point closer at the test engine
    import agents.closer as _closer
    monkeypatch.setattr(_closer, "engine", engine)
    with Session(engine) as s:
        yield s


def _seed_lead(session, **overrides):
    defaults = {
        "company_id": 1,
        "name": "Lokesh Kumar",
        "normalized_phone": "+919876543210",
        "email": "lokesh@example.com",
        "ism_stage": "quoted",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


def _seed_quote(session, lead, sent_days_ago: int | None = 4, status: str = "sent"):
    now = datetime.now(timezone.utc)
    sent_at = None if sent_days_ago is None else now - timedelta(days=sent_days_ago)
    q = Quote(
        company_id=lead.company_id,
        lead_id=lead.id,
        quote_number=f"Q-{lead.id}-{sent_days_ago or 'draft'}",
        status=status,
        currency="INR",
        total_amount=Decimal("10000.00"),
        sent_at=sent_at,
    )
    session.add(q); session.commit(); session.refresh(q)
    return q


def _seed_inbound_reply(session, lead, quote, body: str, minutes_after_send: int = 60):
    base = quote.sent_at or datetime.now(timezone.utc)
    i = Interaction(
        company_id=lead.company_id,
        lead_id=lead.id,
        type="communication",
        channel="email",
        direction="inbound",
        content=body,
        status="completed",
        started_at=base + timedelta(minutes=minutes_after_send),
    )
    session.add(i); session.commit(); session.refresh(i)
    return i


def _call_closer(company_id: int, lead_id: int, quote_id: int, silence_days: int = 4):
    from agents.closer import run
    return asyncio.run(run(
        company_id=company_id,
        actor_user_id=1,
        lead_id=lead_id,
        quote_id=quote_id,
        silence_days=silence_days,
    ))


# Context loading + stale-data guards

def test_skips_when_lead_missing(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead)
    # Soft-delete the lead AFTER seeding
    from models.models import utc_now
    lead.deleted_at = utc_now(); session.add(lead); session.commit()
    result = _call_closer(1, lead.id, quote.id)
    assert result["skipped"] is True
    assert result["reason"] == "context_not_found"


def test_skips_when_quote_accepted(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, status="accepted")
    result = _call_closer(1, lead.id, quote.id)
    assert result["skipped"] is True
    assert result["reason"] == "quote_resolved"


def test_skips_when_quote_rejected(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, status="rejected")
    result = _call_closer(1, lead.id, quote.id)
    assert result["skipped"] is True
    assert result["reason"] == "quote_resolved"


def test_skips_when_lead_closed_won(session):
    lead = _seed_lead(session, ism_stage="closed_won")
    quote = _seed_quote(session, lead)
    result = _call_closer(1, lead.id, quote.id)
    assert result["skipped"] is True
    assert "lead_stage_closed_won" in result["reason"]


# Classification paths — silent

def test_silent_sends_followup(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, sent_days_ago=4)
    result = _call_closer(1, lead.id, quote.id, silence_days=4)
    assert result["outcome"] == "followup_sent"
    assert result["classification"] == "silent"
    task = session.get(AgentTask, result["task_id"])
    assert task is not None
    assert task.task_type == "send_email"
    assert "Following up on" in task.input_json["subject"]
    assert f"closer_silent:{quote.id}:4" == task.idempotency_key


# Classification paths — objection

def test_objection_dispatches_parry_with_rebuttal(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, sent_days_ago=2)
    # Seed an active ObjectionEntry with a rebuttal
    obj = ObjectionEntry(
        company_id=1,
        objection_key="too expensive",
        objection_text="Price is too high",
        category="price",
        rebuttal="Let's walk through the ROI — our customers see payback within 6 months.",
    )
    session.add(obj); session.commit(); session.refresh(obj)
    _seed_inbound_reply(session, lead, quote, "This is too expensive for us right now")
    result = _call_closer(1, lead.id, quote.id, silence_days=2)
    assert result["outcome"] == "objection_parried"
    assert result["rebuttal_id"] == obj.id
    task = session.get(AgentTask, result["task_id"])
    assert task is not None
    assert task.task_type == "send_email"
    assert "payback within 6 months" in task.input_json["body"]


def test_objection_falls_back_without_matching_entry(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, sent_days_ago=2)
    _seed_inbound_reply(session, lead, quote, "we have some concerns and are not sure")
    result = _call_closer(1, lead.id, quote.id, silence_days=2)
    assert result["outcome"] == "objection_parried"
    # No ObjectionEntry seeded — fallback body still sent
    task = session.get(AgentTask, result["task_id"])
    assert "Happy to address" in task.input_json["body"]


# Classification paths — question / ready_to_close

def test_question_creates_answer_task(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, sent_days_ago=1)
    _seed_inbound_reply(session, lead, quote, "How does your onboarding process work for new teams?")
    result = _call_closer(1, lead.id, quote.id, silence_days=1)
    assert result["outcome"] == "question_answered"
    task = session.get(AgentTask, result["task_id"])
    assert "onboarding" in task.input_json["body"]


def test_ready_to_close_advances_lead(session):
    lead = _seed_lead(session, ism_stage="negotiation")
    quote = _seed_quote(session, lead, sent_days_ago=1, status="negotiation")
    _seed_inbound_reply(session, lead, quote, "Yes, let's go. Send the contract!")
    result = _call_closer(1, lead.id, quote.id, silence_days=1)
    assert result["outcome"] == "close_won"
    session.refresh(lead); session.refresh(quote)
    assert lead.ism_stage == "closed_won"
    assert lead.qualification_status == "won"
    assert lead.next_action == "celebrate"
    assert quote.status == "accepted"
    assert quote.accepted_at is not None


def test_many_rounds_triggers_handoff(session):
    lead = _seed_lead(session, ism_stage="negotiation")
    quote = _seed_quote(session, lead, sent_days_ago=1, status="negotiation")
    # 6 inbound replies, final one looks ready-to-close
    for i in range(5):
        _seed_inbound_reply(session, lead, quote, f"round {i} back and forth", minutes_after_send=30 + i * 10)
    _seed_inbound_reply(session, lead, quote, "Yes, let's go ahead and proceed!", minutes_after_send=200)
    result = _call_closer(1, lead.id, quote.id, silence_days=1)
    assert result["outcome"] == "handoff_to_human"
    task = session.get(AgentTask, result["task_id"])
    assert task.task_type == "handoff"
    assert task.requires_approval is True
    assert "stuck after" in task.input_json["reason"]
    assert task.input_json["negotiation_summary"]


# Silence-scan worker helper

def test_silence_scan_returns_quote_sent_4_days_ago(session):
    lead = _seed_lead(session)
    _seed_quote(session, lead, sent_days_ago=4, status="sent")
    from services.automation_worker_service import _enqueue_closer_tasks_for_silent_quotes
    result = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    assert result["enqueued"] == 1


def test_silence_scan_excludes_quote_with_inbound_reply(session):
    lead = _seed_lead(session)
    quote = _seed_quote(session, lead, sent_days_ago=4, status="sent")
    _seed_inbound_reply(session, lead, quote, "got it thanks")
    from services.automation_worker_service import _enqueue_closer_tasks_for_silent_quotes
    result = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    assert result["enqueued"] == 0
    assert any("has_inbound" in s for s in result["skipped"])


def test_silence_scan_excludes_closed_won_lead(session):
    lead = _seed_lead(session, ism_stage="closed_won")
    _seed_quote(session, lead, sent_days_ago=5, status="sent")
    from services.automation_worker_service import _enqueue_closer_tasks_for_silent_quotes
    result = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    assert result["enqueued"] == 0


def test_silence_scan_excludes_accepted_quote(session):
    lead = _seed_lead(session)
    _seed_quote(session, lead, sent_days_ago=4, status="accepted")
    from services.automation_worker_service import _enqueue_closer_tasks_for_silent_quotes
    result = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    assert result["enqueued"] == 0


def test_silence_scan_idempotent_same_day(session):
    lead = _seed_lead(session)
    _seed_quote(session, lead, sent_days_ago=4, status="sent")
    from services.automation_worker_service import _enqueue_closer_tasks_for_silent_quotes
    r1 = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    r2 = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    assert r1["enqueued"] == 1
    # Second run dedupes via idempotency key
    from sqlmodel import select as _select
    tasks = session.exec(
        _select(AgentTask).where(
            AgentTask.company_id == 1,
            AgentTask.task_type == "closer_followup",
        )
    ).all()
    assert len(tasks) == 1
    assert r2["enqueued"] <= 1  # may re-stamp the same task or skip


def test_maybe_enqueue_throttles_within_15_minutes(session, monkeypatch):
    lead = _seed_lead(session)
    _seed_quote(session, lead, sent_days_ago=4, status="sent")
    from services.automation_worker_service import (
        _maybe_enqueue_closer_tasks_for_company,
        _reset_closer_scan_throttle_for_tests,
    )
    _reset_closer_scan_throttle_for_tests()
    first = _maybe_enqueue_closer_tasks_for_company(session, 1, 1)
    second = _maybe_enqueue_closer_tasks_for_company(session, 1, 1)
    assert "enqueued" in first
    assert second.get("skipped") == "throttled_15min"
