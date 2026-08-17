"""Tests for Week 7.2 — Outreacher agent.

The heavy per-channel behavior is exercised by the existing ISM suite
(test_ism_transition.py, test_ism_rules_engine.py). This file covers
outreacher.run's orchestration: load lead → pick_channel → dispatch →
stamp lead. All three dispatch helpers are stubbed so we don't hit Twilio,
SMTP, or the AgentTask queue machinery.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from unittest.mock import patch

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import Lead


# Stubs — avoid importing the real outbound call + send services.
_stub_call = types.ModuleType("call")
_stub_call_outbound = types.ModuleType("call.outbound_call_service")
_stub_call_outbound.create_call_task = lambda **kw: types.SimpleNamespace(id=7)
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
    # Point agents.outreacher at the test engine instead of the real one.
    import agents.outreacher as _outreacher
    monkeypatch.setattr(_outreacher, "engine", engine)
    with Session(engine) as s:
        yield s


def _seed_lead(session, **overrides) -> Lead:
    defaults = {
        "company_id": 1,
        "name": "Test Lead",
        "normalized_phone": "+919876543210",
        "email": "lead@example.com",
        "ism_stage": "new",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


def _call_run(company_id: int, lead_id: int, stage: str | None = None, actor_user_id: int = 1):
    from agents.outreacher import run
    return asyncio.run(run(
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead_id,
        stage=stage,
    ))


# run() orchestration — happy path per channel

def test_run_picks_call_and_dispatches(session, monkeypatch):
    lead = _seed_lead(session, ism_stage="new")
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: "call")
    monkeypatch.setattr(
        "agents.outreacher.dispatch_call",
        lambda *a, **k: {"channel": "call", "action": "queued_call_task", "call_task_id": 42},
    )
    result = _call_run(company_id=1, lead_id=lead.id)
    assert result["channel"] == "call"
    assert result["call_task_id"] == 42
    assert result["skipped"] is False


def test_run_picks_whatsapp_and_dispatches(session, monkeypatch):
    lead = _seed_lead(session, ism_stage="engaged")
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: "whatsapp")
    monkeypatch.setattr(
        "agents.outreacher.dispatch_whatsapp",
        lambda *a, **k: {"channel": "whatsapp", "action": "queued_send_whatsapp", "agent_task_id": 101},
    )
    result = _call_run(company_id=1, lead_id=lead.id)
    assert result["channel"] == "whatsapp"
    assert result["agent_task_id"] == 101


def test_run_picks_email_and_dispatches(session, monkeypatch):
    lead = _seed_lead(session, ism_stage="quoted")
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: "email")
    monkeypatch.setattr(
        "agents.outreacher.dispatch_email",
        lambda *a, **k: {"channel": "email", "action": "queued_send_email", "agent_task_id": 202},
    )
    result = _call_run(company_id=1, lead_id=lead.id)
    assert result["channel"] == "email"
    assert result["agent_task_id"] == 202


# Skip reasons

def test_run_skips_when_all_channels_blocked(session, monkeypatch):
    lead = _seed_lead(session)
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: None)
    result = _call_run(company_id=1, lead_id=lead.id)
    assert result["skipped"] is True
    assert result["skip_reason"] == "all_channels_blocked"


def test_run_skips_when_lead_missing(session):
    result = _call_run(company_id=1, lead_id=99999)
    assert result["skipped"] is True
    assert result["skip_reason"] == "lead_not_found"


def test_run_skips_when_lead_soft_deleted(session, monkeypatch):
    from models.models import utc_now
    lead = _seed_lead(session)
    lead.deleted_at = utc_now()
    session.add(lead); session.commit()
    result = _call_run(company_id=1, lead_id=lead.id)
    assert result["skipped"] is True
    assert result["skip_reason"] == "lead_not_found"


def test_run_returns_error_on_missing_lead_id(session):
    from agents.outreacher import run
    result = asyncio.run(run(company_id=1, actor_user_id=1))
    assert result.get("skipped") is True
    assert "error" in result


# Stage fallback

def test_run_uses_lead_stage_when_stage_arg_missing(session, monkeypatch):
    lead = _seed_lead(session, ism_stage="engaged")
    captured = {}
    def _fake_pick(_s, _c, _l, _stage):
        captured["stage"] = _stage
        return "whatsapp"
    monkeypatch.setattr("agents.outreacher.pick_channel", _fake_pick)
    monkeypatch.setattr(
        "agents.outreacher.dispatch_whatsapp",
        lambda *a, **k: {"channel": "whatsapp", "action": "queued_send_whatsapp"},
    )
    _call_run(company_id=1, lead_id=lead.id)
    assert captured["stage"] == "engaged"


def test_run_uses_explicit_stage_override(session, monkeypatch):
    lead = _seed_lead(session, ism_stage="new")
    captured = {}
    def _fake_pick(_s, _c, _l, _stage):
        captured["stage"] = _stage
        return None
    monkeypatch.setattr("agents.outreacher.pick_channel", _fake_pick)
    _call_run(company_id=1, lead_id=lead.id, stage="quoted")
    assert captured["stage"] == "quoted"


def test_run_defaults_to_new_when_stage_and_lead_stage_missing(session, monkeypatch):
    lead = _seed_lead(session, ism_stage=None)
    captured = {}
    def _fake_pick(_s, _c, _l, _stage):
        captured["stage"] = _stage
        return None
    monkeypatch.setattr("agents.outreacher.pick_channel", _fake_pick)
    _call_run(company_id=1, lead_id=lead.id)
    assert captured["stage"] == "new"


# Error handling

def test_run_catches_dispatch_exception(session, monkeypatch):
    lead = _seed_lead(session)
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: "whatsapp")
    def _boom(*a, **k):
        raise RuntimeError("twilio down")
    monkeypatch.setattr("agents.outreacher.dispatch_whatsapp", _boom)
    result = _call_run(company_id=1, lead_id=lead.id)
    assert result["channel"] == "whatsapp"
    assert "twilio down" in result["error"]
    assert result["skipped"] is False


def test_run_stamps_last_outreach_at(session, monkeypatch):
    lead = _seed_lead(session)
    assert lead.last_outreach_at is None
    monkeypatch.setattr("agents.outreacher.pick_channel", lambda *a, **k: "call")
    monkeypatch.setattr(
        "agents.outreacher.dispatch_call",
        lambda *a, **k: {"channel": "call", "action": "queued_call_task", "call_task_id": 1},
    )
    _call_run(company_id=1, lead_id=lead.id)
    session.refresh(lead)
    assert lead.last_outreach_at is not None


# Re-exports still point at ism_orchestrator

def test_pick_channel_is_re_exported():
    from agents import outreacher
    from agents import ism_orchestrator
    # pick_channel is a wrapper; confirm the underlying call goes to ism_orch.
    assert outreacher._ism_pick_channel is ism_orchestrator._pick_channel
