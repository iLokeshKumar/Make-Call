"""Integration tests for Week 3.3b — rules engine inside run_ism_cycle.

Locks down:
  1. With no active rules, run_ism_cycle behavior is identical to pre-3.3
  2. advance_to:<stage> rule → lead advances, no dispatch
  3. handoff_to_human rule → AgentTask(requires_approval=True) created;
     operator sees it in approvals inbox; no dispatch
  4. dispatch:call override → forces call channel even if stage default
     says otherwise
  5. dispatch:<channel> but channel is unavailable → falls through to
     _pick_channel (not silently broken)
  6. Rule metadata (id + name) surfaces in the result dict for observability
  7. Handoff is idempotent: same lead/stage/rule combo creates one task, not N
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

from datetime import timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import AgentTask, IsmRule, Lead, utc_now


@pytest.fixture(autouse=True)
def _queue_on(monkeypatch):
    # Keep the dispatch_service queue path enabled so matching rules can
    # dispatch through the AgentTask system during tests.
    monkeypatch.setenv("USE_AGENT_TASK_QUEUE", "1")


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
        "company_id": 1,
        "name": "Test Lead",
        "normalized_phone": "+919876543210",
        "email": "lead@example.com",
        "ism_stage": "engaged",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


def _seed_rule(session, **overrides):
    defaults = {
        "company_id": 1, "name": "test-rule", "priority": 10,
        "when_json": {}, "then_action": "skip", "is_active": True,
    }
    defaults.update(overrides)
    rule = IsmRule(**defaults)
    session.add(rule); session.commit(); session.refresh(rule)
    return rule


def _import_run_ism_cycle():
    """Import here so the conftest stubs + env are set before side effects."""
    from agents.ism_orchestrator import run_ism_cycle
    return run_ism_cycle


# Backward-compat — no rules = existing behavior

class TestNoRulesPreservesOldBehavior:
    def test_no_rules_triggers_normal_dispatch(self, session):
        lead = _seed_lead(session, ism_stage="engaged")
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        # No rules exist → should proceed with normal channel selection
        assert result["lead_id"] == lead.id
        assert "rule_id" not in result
        assert result.get("skipped") is False or result.get("channel") is not None


# advance_to

class TestAdvanceToRule:
    def test_rule_advances_stage_without_dispatch(self, session):
        lead = _seed_lead(session, ism_stage="engaged")
        rule = _seed_rule(
            session,
            name="engaged_to_negotiation",
            priority=1,
            when_json={"stage": "engaged"},
            then_action="advance_to:negotiation",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        assert result["skipped"] is True
        assert result["skip_reason"] == "rule_advanced_stage"
        assert result["rule_id"] == rule.id
        assert result["rule_name"] == "engaged_to_negotiation"

        session.refresh(lead)
        assert lead.ism_stage == "negotiation"

    def test_invalid_advance_to_stage_falls_through(self, session):
        """If a rule tries to advance to a non-existent stage, rule engine
        falls through to normal dispatch rather than corrupting lead state."""
        lead = _seed_lead(session, ism_stage="engaged")
        _seed_rule(
            session, name="broken_rule",
            when_json={"stage": "engaged"},
            then_action="advance_to:nonsense_stage",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        session.refresh(lead)
        assert lead.ism_stage == "engaged"  # unchanged


# handoff_to_human

class TestHandoffRule:
    def test_handoff_creates_approval_task(self, session):
        lead = _seed_lead(session, ism_stage="negotiation")
        rule = _seed_rule(
            session, name="stuck_negotiation",
            when_json={"stage": "negotiation"},
            then_action="handoff_to_human",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        assert result["skipped"] is True
        assert result["skip_reason"] == "rule_handoff_to_human"
        assert result["rule_id"] == rule.id

        # An AgentTask should exist with task_type='handoff' and requires_approval=True
        tasks = session.exec(
            select(AgentTask).where(AgentTask.task_type == "handoff")
        ).all()
        assert len(tasks) == 1
        assert tasks[0].requires_approval is True
        assert tasks[0].lead_id == lead.id
        assert tasks[0].input_json["rule_id"] == rule.id
        assert "summary" in tasks[0].input_json

    def test_handoff_is_idempotent(self, session):
        """Running the same cycle twice should NOT create two handoff tasks."""
        lead = _seed_lead(session, ism_stage="negotiation")
        _seed_rule(
            session, name="stuck", when_json={"stage": "negotiation"},
            then_action="handoff_to_human",
        )
        run_ism_cycle = _import_run_ism_cycle()
        run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)
        # Move last_outreach_at back so global cooldown doesn't interfere
        lead.last_outreach_at = None
        session.add(lead); session.commit()
        run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        tasks = session.exec(
            select(AgentTask).where(AgentTask.task_type == "handoff")
        ).all()
        assert len(tasks) == 1  # dedupe via idempotency_key


# dispatch:<channel> override

class TestDispatchChannelOverride:
    def test_dispatch_call_forces_call_channel(self, session):
        """Stage 'engaged' default prefers email; rule forces call."""
        lead = _seed_lead(session, ism_stage="engaged")
        _seed_rule(
            session, name="force_call_on_engaged",
            when_json={"stage": "engaged"},
            then_action="dispatch:call",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        # Result should show channel=call, not email (which is the stage default)
        assert result.get("channel") == "call"

    def test_dispatch_channel_override_respects_guards(self, session):
        """Rule forces whatsapp, but lead has no phone → falls through to
        normal picker which will choose email (or whatever's available)."""
        lead = _seed_lead(session, ism_stage="engaged", normalized_phone="")
        _seed_rule(
            session, name="force_whatsapp",
            when_json={"stage": "engaged"},
            then_action="dispatch:whatsapp",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        # whatsapp needs phone; lead has none → fall back to _pick_channel
        # → picks email (stage-default for engaged with no phone)
        assert result.get("channel") != "whatsapp"
        # Either picks email or skips (if no channel available)
        assert result.get("channel") == "email" or result.get("skipped") is True


# skip action

class TestSkipRule:
    def test_skip_action_does_nothing(self, session):
        lead = _seed_lead(session)
        rule = _seed_rule(
            session, name="test_noop",
            when_json={"stage": "engaged"},
            then_action="skip",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        assert result["skipped"] is True
        assert result["skip_reason"] == "rule_action_skip"
        assert result["rule_id"] == rule.id

    def test_inactive_rule_does_not_fire(self, session):
        """Disabled rules don't match even if conditions are satisfied."""
        lead = _seed_lead(session)
        _seed_rule(
            session, name="disabled_rule", is_active=False,
            when_json={}, then_action="handoff_to_human",
        )
        run_ism_cycle = _import_run_ism_cycle()
        result = run_ism_cycle(session, company_id=1, lead_id=lead.id, actor_user_id=0)

        assert "rule_id" not in result  # no rule fired
        # No handoff task created
        tasks = session.exec(
            select(AgentTask).where(AgentTask.task_type == "handoff")
        ).all()
        assert len(tasks) == 0
