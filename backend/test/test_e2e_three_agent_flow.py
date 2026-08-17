"""End-to-end Week 7 acceptance: fresh Lead → researcher → outreacher → closer.

Validates the whole pipeline without any per-lead code change:
  1. trigger_new_lead_outreach enqueues a researcher AgentTask.
  2. Researcher's _persist_signals_and_qualify enqueues an outreacher task.
  3. Outreacher picks a channel + dispatches (stubbed).
  4. A Quote is sent, 4 days pass, the silence scan enqueues a closer task.
  5. Closer classifies 'ready_to_close' from a positive inbound reply and
     advances the lead to closed_won.
  6. Closer handoff path is exercised via a separate 'stuck negotiation' lead.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import AgentTask, Interaction, Lead, Quote


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
    # Both outreacher and closer read module-level `engine` — redirect them.
    import agents.outreacher as _outreacher
    import agents.closer as _closer
    monkeypatch.setattr(_outreacher, "engine", engine)
    monkeypatch.setattr(_closer, "engine", engine)
    with Session(engine) as s:
        yield s


def _seed_lead(session, **overrides):
    defaults = {
        "company_id": 1,
        "name": "E2E Lead",
        "normalized_phone": "+919876500000",
        "email": "e2e@example.com",
        "ism_stage": "new",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


def test_researcher_outreacher_closer_flow_end_to_end(session, monkeypatch):
    # Stubs — avoid Apollo, scoring heuristics, dispatch side-effects.
    monkeypatch.setattr(
        "services.leads.demand_generation_service._auto_trigger_enabled",
        lambda *_a, **_kw: True,
    )
    monkeypatch.setattr(
        "services.leads.demand_generation_service.enrich_lead_if_needed",
        lambda *a, **kw: {"updated": False},
    )
    monkeypatch.setattr(
        "services.leads.demand_generation_service.score_lead",
        lambda *a, **kw: {"score": 0.9, "signals": {"pain_points": ["slow tools"]}},
    )
    monkeypatch.setattr(
        "services.leads.demand_generation_service.choose_outreach_strategy",
        lambda *a, **kw: {"schedule_call": False, "strategy": "nurture", "delay_minutes": 0},
    )

    # Step 1: insert lead + trigger
    lead = _seed_lead(session)
    from services.leads.demand_generation_service import trigger_new_lead_outreach
    trigger_result = trigger_new_lead_outreach(session, company_id=1, actor_user_id=1, lead_id=lead.id)
    assert trigger_result["researcher_task_enqueued"] is True

    # Step 2: researcher task in queue — verify its shape
    researcher_tasks = session.exec(
        select(AgentTask).where(
            AgentTask.lead_id == lead.id,
            AgentTask.assigned_agent == "researcher",
        )
    ).all()
    assert len(researcher_tasks) == 1
    assert researcher_tasks[0].task_type == "enrich_lead"

    # Step 3: simulate researcher's qualification step (skip the LangGraph run)
    from agents.researcher import _persist_signals_and_qualify
    q_summary = _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.9, "signals": {"pain_points": ["slow tools"]}},
        icp_score=0.9,
    )
    assert q_summary["qualified"] is True
    assert "outreacher_task_id" in q_summary

    outreacher_tasks = session.exec(
        select(AgentTask).where(
            AgentTask.lead_id == lead.id,
            AgentTask.assigned_agent == "outreacher",
        )
    ).all()
    assert len(outreacher_tasks) == 1
    assert outreacher_tasks[0].task_type == "qualify_lead"

    # Step 4: outreacher.run picks a channel and dispatches (stubbed)
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: "email")
    monkeypatch.setattr(
        "agents.outreacher.dispatch_email",
        lambda *a, **k: {"channel": "email", "action": "queued_send_email", "agent_task_id": 1234},
    )
    from agents.outreacher import run as outreacher_run
    outreacher_result = asyncio.run(outreacher_run(
        company_id=1, actor_user_id=1, lead_id=lead.id, stage="new",
    ))
    assert outreacher_result["channel"] == "email"
    assert outreacher_result["agent_task_id"] == 1234

    # Step 5: simulate a sent quote from 4 days ago + inbound positive reply
    sent_at = datetime.now(timezone.utc) - timedelta(days=4)
    quote = Quote(
        company_id=1, lead_id=lead.id,
        quote_number=f"QE2E-{lead.id}", status="sent",
        currency="INR", total_amount=Decimal("50000.00"),
        sent_at=sent_at,
    )
    session.add(quote); session.commit(); session.refresh(quote)

    # Silence scan enqueues a closer task
    from services.automation_worker_service import (
        _enqueue_closer_tasks_for_silent_quotes,
        _reset_closer_scan_throttle_for_tests,
    )
    _reset_closer_scan_throttle_for_tests()
    scan_result = _enqueue_closer_tasks_for_silent_quotes(session, company_id=1, actor_user_id=1)
    assert scan_result["enqueued"] == 1

    closer_tasks = session.exec(
        select(AgentTask).where(
            AgentTask.assigned_agent == "closer",
            AgentTask.lead_id == lead.id,
        )
    ).all()
    assert len(closer_tasks) == 1

    # Step 6: inbound reply + closer run → close_won
    inbound = Interaction(
        company_id=1, lead_id=lead.id,
        type="communication", channel="email", direction="inbound",
        content="Yes, let's go ahead — send the contract!",
        status="completed",
        started_at=sent_at + timedelta(hours=2),
    )
    session.add(inbound); session.commit()

    from agents.closer import run as closer_run
    close_result = asyncio.run(closer_run(
        company_id=1, actor_user_id=1, lead_id=lead.id, quote_id=quote.id, silence_days=4,
    ))
    assert close_result["outcome"] == "close_won"

    session.refresh(lead); session.refresh(quote)
    assert lead.ism_stage == "closed_won"
    assert lead.qualification_status == "won"
    assert quote.status == "accepted"
    assert quote.accepted_at is not None


def test_closer_handoff_path_creates_approval_task(session):
    lead = _seed_lead(session, ism_stage="negotiation")
    sent_at = datetime.now(timezone.utc) - timedelta(days=1)
    quote = Quote(
        company_id=1, lead_id=lead.id,
        quote_number=f"QH-{lead.id}", status="negotiation",
        currency="INR", total_amount=Decimal("100000.00"),
        sent_at=sent_at,
    )
    session.add(quote); session.commit(); session.refresh(quote)

    # 6 inbound replies — final one reads positive but we're well past _MAX_NEGOTIATION_ROUNDS
    for i in range(5):
        session.add(Interaction(
            company_id=1, lead_id=lead.id,
            type="communication", channel="email", direction="inbound",
            content=f"round {i}: still thinking about it", status="completed",
            started_at=sent_at + timedelta(hours=i + 1),
        ))
    session.add(Interaction(
        company_id=1, lead_id=lead.id,
        type="communication", channel="email", direction="inbound",
        content="Yes, let's go!", status="completed",
        started_at=sent_at + timedelta(hours=10),
    ))
    session.commit()

    from agents.closer import run as closer_run
    result = asyncio.run(closer_run(
        company_id=1, actor_user_id=1, lead_id=lead.id, quote_id=quote.id, silence_days=1,
    ))
    assert result["outcome"] == "handoff_to_human"
    task = session.get(AgentTask, result["task_id"])
    assert task.task_type == "handoff"
    assert task.requires_approval is True
    assert "negotiation_summary" in task.input_json
