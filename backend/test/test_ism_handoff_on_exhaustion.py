"""Tests for the ISM channel-exhausted handoff fix.

Pre-fix bug: when `_pick_channel` returned None at stage=`negotiation`, the
orchestrator called `_advance_stage`, which mechanically promoted the lead
to `closed_won` (next entry in ISM_STAGE_ORDER).  These tests pin the
fixed behaviour: the lead stays in its current stage and a `handoff`
AgentTask is enqueued for human review.
"""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

# Stub provider SDKs that ism_orchestrator drags in transitively.
for _missing in ("groq", "anthropic", "google", "google.generativeai", "cerebras", "openai", "pyotp", "qrcode"):
    if _missing not in sys.modules:
        sys.modules[_missing] = types.ModuleType(_missing)

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select


@pytest.fixture
def engine():
    # Pop bare-stub modules that other test files may have injected so real
    # SDKs win when we hit code paths that need them.
    for _name in (
        "groq", "anthropic", "google", "google.generativeai", "cerebras", "openai",
        "pyotp", "qrcode",
    ):
        mod = sys.modules.get(_name)
        if mod is not None and getattr(mod, "__file__", None) is None and not getattr(mod, "__path__", None):
            sys.modules.pop(_name, None)

    import models.models  # noqa: F401
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


def _seed_company(session, company_id: int = 1):
    from models.models import Company
    c = Company(id=company_id, name=f"C{company_id}", slug=f"c{company_id}")
    session.add(c)
    session.commit()
    return c


def _seed_lead(session, *, lead_id: int, company_id: int, stage: str):
    from models.models import Lead
    lead = Lead(
        id=lead_id,
        company_id=company_id,
        name=f"Lead {lead_id}",
        normalized_phone=f"+1555000{lead_id:04d}",
        ism_stage=stage,
    )
    session.add(lead)
    session.commit()
    return lead


def _seed_feedback(session, *, lead_id: int, company_id: int, rating: int):
    from models.models import Feedback
    fb = Feedback(
        company_id=company_id,
        lead_id=lead_id,
        feedback_type="csat",
        source="customer",
        rating=rating,
        status="submitted",
    )
    session.add(fb)
    session.commit()


def _seed_appointment(session, *, lead_id: int, company_id: int, days_ahead: int = 7, status: str = "scheduled"):
    from datetime import datetime, timedelta, timezone
    from models.models import Appointment
    appt = Appointment(
        company_id=company_id,
        lead_id=lead_id,
        appointment_time=datetime.now(timezone.utc) + timedelta(days=days_ahead),
        status=status,
    )
    session.add(appt)
    session.commit()


def _seed_quote(session, *, lead_id: int, company_id: int, status: str, qid: int):
    from models.models import Quote
    q = Quote(
        id=qid,
        company_id=company_id,
        lead_id=lead_id,
        quote_number=f"Q{qid}",
        status=status,
    )
    session.add(q)
    session.commit()


def test_exhaustion_with_no_signals_auto_closes_lost(session, monkeypatch):
    """Default for silent leads: auto closed_lost — automation-first, no human."""
    _seed_company(session)
    lead = _seed_lead(session, lead_id=1, company_id=1, stage="negotiation")

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    result = ism_orchestrator.run_ism_cycle(
        session=session, company_id=1, lead_id=1, actor_user_id=0,
    )

    session.refresh(lead)
    assert lead.ism_stage == "closed_lost"
    assert result.get("advanced_to_stage") == "closed_lost"
    assert "no_engagement_signals" in result.get("decision_reason", "")


def test_exhaustion_with_high_csat_auto_closes_won(session, monkeypatch):
    _seed_company(session)
    lead = _seed_lead(session, lead_id=2, company_id=1, stage="negotiation")
    _seed_feedback(session, lead_id=2, company_id=1, rating=5)

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    result = ism_orchestrator.run_ism_cycle(
        session=session, company_id=1, lead_id=2, actor_user_id=0,
    )
    session.refresh(lead)
    assert lead.ism_stage == "closed_won"
    assert "verbal_csat=5" in result.get("decision_reason", "")


def test_exhaustion_with_low_csat_auto_closes_lost(session, monkeypatch):
    _seed_company(session)
    lead = _seed_lead(session, lead_id=3, company_id=1, stage="negotiation")
    _seed_feedback(session, lead_id=3, company_id=1, rating=1)

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    result = ism_orchestrator.run_ism_cycle(
        session=session, company_id=1, lead_id=3, actor_user_id=0,
    )
    session.refresh(lead)
    assert lead.ism_stage == "closed_lost"
    assert "verbal_csat=1" in result.get("decision_reason", "")


def test_exhaustion_with_accepted_quote_auto_closes_won(session, monkeypatch):
    _seed_company(session)
    lead = _seed_lead(session, lead_id=4, company_id=1, stage="negotiation")
    _seed_quote(session, lead_id=4, company_id=1, status="accepted", qid=1001)

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    result = ism_orchestrator.run_ism_cycle(
        session=session, company_id=1, lead_id=4, actor_user_id=0,
    )
    session.refresh(lead)
    assert lead.ism_stage == "closed_won"
    assert "quote_accepted" in result.get("decision_reason", "")


def test_exhaustion_with_conflicting_signals_creates_handoff(session, monkeypatch):
    """High CSAT + not_interested qualification = ambiguous → handoff (only here)."""
    _seed_company(session)
    lead = _seed_lead(session, lead_id=5, company_id=1, stage="negotiation")
    _seed_feedback(session, lead_id=5, company_id=1, rating=5)
    lead.qualification_status = "not_interested"
    session.add(lead); session.commit()

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    result = ism_orchestrator.run_ism_cycle(
        session=session, company_id=1, lead_id=5, actor_user_id=0,
    )
    session.refresh(lead)
    # Lead stays at negotiation — neither auto-close fired.
    assert lead.ism_stage == "negotiation"
    assert result.get("handoff_created") is True

    from models.models import AgentTask
    rows = session.exec(
        select(AgentTask).where(
            AgentTask.lead_id == 5,
            AgentTask.task_type == "handoff",
        )
    ).all()
    assert len(rows) == 1
    assert rows[0].input_json.get("reason") == "ambiguous_signals"


def test_exhaustion_handoff_is_idempotent(session, monkeypatch):
    """Ambiguous-handoff path: running cycle twice creates one handoff."""
    _seed_company(session)
    lead = _seed_lead(session, lead_id=6, company_id=1, stage="negotiation")
    _seed_feedback(session, lead_id=6, company_id=1, rating=5)
    lead.qualification_status = "not_interested"
    session.add(lead); session.commit()

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    ism_orchestrator.run_ism_cycle(session=session, company_id=1, lead_id=6, actor_user_id=0)
    ism_orchestrator.run_ism_cycle(session=session, company_id=1, lead_id=6, actor_user_id=0)

    from models.models import AgentTask
    rows = session.exec(
        select(AgentTask).where(
            AgentTask.lead_id == 6,
            AgentTask.task_type == "handoff",
        )
    ).all()
    assert len(rows) == 1


def test_exhaustion_with_future_demo_auto_closes_won_when_combined_with_csat(session, monkeypatch):
    """Future appointment alone is +1, csat>=4 is +2 → 3 total positive, no negative."""
    _seed_company(session)
    lead = _seed_lead(session, lead_id=7, company_id=1, stage="negotiation")
    _seed_appointment(session, lead_id=7, company_id=1, days_ahead=5)
    _seed_feedback(session, lead_id=7, company_id=1, rating=4)

    from agents import ism_orchestrator
    monkeypatch.setattr(ism_orchestrator, "_pick_channel", lambda *a, **kw: None)

    result = ism_orchestrator.run_ism_cycle(
        session=session, company_id=1, lead_id=7, actor_user_id=0,
    )
    session.refresh(lead)
    assert lead.ism_stage == "closed_won"
    assert "future_demo_booked" in result.get("decision_reason", "")
