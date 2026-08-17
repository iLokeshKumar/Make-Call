"""Tests for Week 2.3 — webhook audit enqueue pattern.

Three invariants:
  1. Audit creates an AgentTask with correct shape (task_type, assigned_agent,
     idempotency_key derived from event_type + provider_event_id + extra)
  2. Replay of same (event_type, provider_event_id, extra) dedupes — Twilio
     retry can't double-audit
  3. Enqueue NEVER raises. Even with bogus inputs / missing session commit,
     it returns None and logs. Webhook handlers must never fail on audit.

Plus: webhook_sink.run is a no-op that returns ok=True (Phase 1 contract).
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import AgentTask
from services.agent.webhook_audit_service import (
    _make_audit_key,
    enqueue_webhook_audit,
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


# Invariant 1: audit task shape

class TestAuditShape:
    def test_creates_task_with_webhook_audit_type(self, session):
        task = enqueue_webhook_audit(
            session,
            company_id=1,
            event_type="twilio_call_status",
            provider_event_id="CA123abc",
            payload={"CallStatus": "completed"},
            extra="completed",
        )
        assert task is not None
        assert task.task_type == "webhook_audit"
        assert task.assigned_agent == "webhook_sink"
        assert task.requires_approval is False
        assert task.input_json["event_type"] == "twilio_call_status"
        assert task.input_json["provider_event_id"] == "CA123abc"
        assert task.input_json["payload"] == {"CallStatus": "completed"}

    def test_lead_id_stored_when_provided(self, session):
        task = enqueue_webhook_audit(
            session,
            company_id=1, event_type="quote_accept",
            provider_event_id="q123", payload={}, lead_id=42,
        )
        assert task.lead_id == 42


# Invariant 2: dedup on replay

class TestReplayDedup:
    def test_same_event_same_extra_dedupes(self, session):
        first = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_call_status", provider_event_id="CA1",
            payload={"s": 1}, extra="ringing",
        )
        # Simulate Twilio retry with the SAME CallSid + CallStatus
        second = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_call_status", provider_event_id="CA1",
            payload={"s": 1}, extra="ringing",
        )
        assert first.id == second.id
        assert len(session.exec(select(AgentTask)).all()) == 1

    def test_same_event_different_extra_creates_new(self, session):
        """Twilio sends multiple CallStatus updates per CallSid — ringing,
        in-progress, completed. Each must be a separate audit row."""
        ringing = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_call_status", provider_event_id="CA1",
            payload={}, extra="ringing",
        )
        completed = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_call_status", provider_event_id="CA1",
            payload={}, extra="completed",
        )
        assert ringing.id != completed.id

    def test_different_provider_event_creates_new(self, session):
        a = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_whatsapp_inbound", provider_event_id="SM1",
            payload={},
        )
        b = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_whatsapp_inbound", provider_event_id="SM2",
            payload={},
        )
        assert a.id != b.id

    def test_key_is_deterministic(self):
        """Same inputs produce the same key across calls."""
        k1 = _make_audit_key("twilio_call_status", "CA1", "completed")
        k2 = _make_audit_key("twilio_call_status", "CA1", "completed")
        assert k1 == k2

    def test_key_fits_200_char_column(self):
        """Even with pathologically long inputs, key stays under AgentTask column limit."""
        key = _make_audit_key(
            "very_long_event_type" * 10,
            "very_long_provider_event_id" * 10,
            "very_long_extra" * 10,
        )
        assert len(key) <= 200


# Invariant 3: never raises

class TestNeverRaises:
    def test_returns_none_on_internal_failure(self, monkeypatch, session):
        """If create_agent_task raises, enqueue_webhook_audit returns None."""
        import services.agent.webhook_audit_service as mod

        def boom(*args, **kwargs):
            raise RuntimeError("simulated DB outage")

        monkeypatch.setattr(
            "services.agent.agent_task_service.create_agent_task",
            boom,
        )

        result = enqueue_webhook_audit(
            session, company_id=1,
            event_type="twilio_call_status", provider_event_id="CA1",
            payload={},
        )
        assert result is None  # swallowed — webhook handler continues


# webhook_sink executor contract

class TestWebhookSinkNoOp:
    @pytest.mark.asyncio
    async def test_sink_returns_ok(self):
        from agents.webhook_sink import run
        result = await run(
            company_id=1, actor_user_id=0, lead_id=42,
            task_type="webhook_audit",
            event_type="twilio_call_status",
            provider_event_id="CA1",
            extra="completed",
            payload={"CallStatus": "completed"},
        )
        assert result["ok"] is True
        assert result["sink"] == "noop"
        assert result["event_type"] == "twilio_call_status"

    @pytest.mark.asyncio
    async def test_sink_handles_missing_fields(self):
        """Sink must not crash on partial/malformed input — audit log is
        a best-effort record; executor robustness is key."""
        from agents.webhook_sink import run
        result = await run(company_id=1)
        assert result["ok"] is True
