"""Tests for Week 7.1 — Researcher agent extension.

Covers the pure helpers (_coerce_list, _get_qualify_threshold) and the
persistence/qualification logic (_persist_signals_and_qualify), which is the
new behavior the roadmap requires. The LangGraph `run()` wrapper is tested
via E2E flow, not here.
"""
from __future__ import annotations

import os
import sys
import types
from unittest.mock import patch

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import AgentTask, Lead, LeadRequirement


# Stubs to bypass create_call_task etc. during trigger_new_lead_outreach tests.
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
def session(engine):
    with Session(engine) as s:
        yield s


def _seed_lead(session, **overrides) -> Lead:
    defaults = {
        "company_id": 1,
        "name": "Test Lead",
        "normalized_phone": "+919876543210",
        "email": "lead@example.com",
        "ism_stage": "new",
        "qualification_status": "unqualified",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


# _coerce_list

def test_coerce_list_handles_none():
    from agents.researcher import _coerce_list
    assert _coerce_list(None) is None


def test_coerce_list_handles_string():
    from agents.researcher import _coerce_list
    assert _coerce_list("budget concerns") == "budget concerns"


def test_coerce_list_handles_empty_string():
    from agents.researcher import _coerce_list
    assert _coerce_list("") is None
    assert _coerce_list("   ") is None


def test_coerce_list_joins_list_of_strings():
    from agents.researcher import _coerce_list
    assert _coerce_list(["price", "timing"]) == "price, timing"


def test_coerce_list_filters_empty_items():
    from agents.researcher import _coerce_list
    assert _coerce_list(["a", "", None, "b"]) == "a, b"


# _get_qualify_threshold

def test_qualify_threshold_defaults_to_half(session):
    from agents.researcher import _get_qualify_threshold
    assert _get_qualify_threshold(session, company_id=1) == 0.5


def test_qualify_threshold_reads_company_setting(session, monkeypatch):
    stub = types.ModuleType("credentials_service")
    stub.get_company_setting_value = lambda _s, _c, _k: "0.8"
    monkeypatch.setitem(sys.modules, "credentials_service", stub)
    from agents.researcher import _get_qualify_threshold
    assert _get_qualify_threshold(session, company_id=1) == 0.8


# _persist_signals_and_qualify — qualify path

def test_qualify_path_enqueues_outreacher_task(session):
    lead = _seed_lead(session, ism_stage="new")
    from agents.researcher import _persist_signals_and_qualify

    summary = _persist_signals_and_qualify(
        session=session,
        company_id=1,
        lead_id=lead.id,
        actor_user_id=1,
        scoring_result={
            "score": 0.9,
            "signals": {"pain_points": ["slow onboarding"]},
        },
        icp_score=0.9,
    )

    assert summary["qualified"] is True
    assert summary["threshold"] == 0.5
    assert "outreacher_task_id" in summary
    task = session.get(AgentTask, summary["outreacher_task_id"])
    assert task is not None
    assert task.assigned_agent == "outreacher"
    assert task.task_type == "qualify_lead"
    assert task.input_json["lead_id"] == lead.id


def test_disqualify_path_marks_lead(session):
    lead = _seed_lead(session, ism_stage="new")
    from agents.researcher import _persist_signals_and_qualify

    summary = _persist_signals_and_qualify(
        session=session,
        company_id=1,
        lead_id=lead.id,
        actor_user_id=1,
        scoring_result={"score": 0.2, "signals": {}},
        icp_score=0.2,
    )

    assert summary["qualified"] is False
    session.refresh(lead)
    assert lead.qualification_status == "disqualified"
    assert lead.ism_stage == "closed_lost"


def test_custom_threshold_below_score_still_disqualifies(session, monkeypatch):
    stub = types.ModuleType("credentials_service")
    stub.get_company_setting_value = lambda _s, _c, _k: "0.8"
    monkeypatch.setitem(sys.modules, "credentials_service", stub)

    lead = _seed_lead(session, ism_stage="new")
    from agents.researcher import _persist_signals_and_qualify

    summary = _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.7}, icp_score=0.7,
    )

    assert summary["qualified"] is False
    session.refresh(lead)
    assert lead.ism_stage == "closed_lost"


def test_requirement_persisted_when_signals_present(session):
    lead = _seed_lead(session)
    from agents.researcher import _persist_signals_and_qualify

    _persist_signals_and_qualify(
        session=session,
        company_id=1,
        lead_id=lead.id,
        actor_user_id=1,
        scoring_result={
            "score": 0.9,
            "signals": {
                "pain_points": ["manual processes", "slow response"],
                "budget_range": "$50-100k",
                "timeline": "Q2",
            },
        },
        icp_score=0.9,
    )

    from sqlmodel import select
    req = session.exec(
        select(LeadRequirement).where(
            LeadRequirement.lead_id == lead.id,
            LeadRequirement.company_id == 1,
        )
    ).first()
    assert req is not None
    assert req.pain_points == "manual processes, slow response"
    assert req.budget_range == "$50-100k"
    assert req.timeline == "Q2"


def test_no_requirement_written_when_signals_empty(session):
    lead = _seed_lead(session)
    from agents.researcher import _persist_signals_and_qualify

    _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.9, "signals": {}}, icp_score=0.9,
    )

    from sqlmodel import select
    req = session.exec(
        select(LeadRequirement).where(LeadRequirement.lead_id == lead.id)
    ).first()
    assert req is None


def test_lead_missing_returns_skipped_summary(session):
    from agents.researcher import _persist_signals_and_qualify
    summary = _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=9999, actor_user_id=1,
        scoring_result={"score": 0.9}, icp_score=0.9,
    )
    assert summary.get("skipped") == "lead_not_found"


def test_outreacher_enqueue_idempotent(session):
    lead = _seed_lead(session, ism_stage="new")
    from agents.researcher import _persist_signals_and_qualify

    s1 = _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.9}, icp_score=0.9,
    )
    s2 = _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.9}, icp_score=0.9,
    )

    # Both calls succeed but the idempotency key `outreacher:{lead_id}:{stage}`
    # dedupes — the second should return the already-enqueued task.
    assert s1.get("outreacher_task_id") == s2.get("outreacher_task_id")


def test_requirement_upsert_updates_existing(session):
    lead = _seed_lead(session)
    from agents.researcher import _persist_signals_and_qualify

    _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.9, "signals": {"pain_points": ["old pain"]}},
        icp_score=0.9,
    )
    _persist_signals_and_qualify(
        session=session, company_id=1, lead_id=lead.id, actor_user_id=1,
        scoring_result={"score": 0.9, "signals": {"pain_points": ["new pain", "another"]}},
        icp_score=0.9,
    )

    from sqlmodel import select
    rows = session.exec(
        select(LeadRequirement).where(LeadRequirement.lead_id == lead.id)
    ).all()
    assert len(rows) == 1
    assert rows[0].pain_points == "new pain, another"


# trigger_new_lead_outreach — researcher auto-enqueue

def test_trigger_new_lead_enqueues_researcher_task(session, monkeypatch):
    lead = _seed_lead(session)

    # Make AUTO_TRIGGER_NEW_LEADS return True.
    monkeypatch.setattr(
        "services.leads.demand_generation_service._auto_trigger_enabled",
        lambda *_a, **_kw: True,
    )
    # Stub enrichment + scoring so we don't hit real Apollo or heuristics.
    monkeypatch.setattr(
        "services.leads.demand_generation_service.enrich_lead_if_needed",
        lambda *a, **kw: {"updated": False},
    )
    monkeypatch.setattr(
        "services.leads.demand_generation_service.score_lead",
        lambda *a, **kw: {"score": 0.9, "signals": {}},
    )
    monkeypatch.setattr(
        "services.leads.demand_generation_service.choose_outreach_strategy",
        lambda *a, **kw: {"schedule_call": False, "strategy": "nurture", "delay_minutes": 0},
    )

    from services.leads.demand_generation_service import trigger_new_lead_outreach
    result = trigger_new_lead_outreach(session, company_id=1, actor_user_id=1, lead_id=lead.id)

    assert result.get("researcher_task_enqueued") is True

    from sqlmodel import select
    tasks = session.exec(
        select(AgentTask).where(
            AgentTask.lead_id == lead.id,
            AgentTask.assigned_agent == "researcher",
        )
    ).all()
    assert len(tasks) == 1
    assert tasks[0].task_type == "enrich_lead"
    assert tasks[0].idempotency_key == f"researcher:{lead.id}"
