"""Tests for Week 2.2 — enqueue helpers + send executor.

Four invariants locked down:
  1. Queue-enabled path creates an AgentTask with the right shape
  2. Duplicate enqueue (same trigger + same lead + same content) dedupes
  3. Different trigger/content → new task (no over-aggressive dedup)
  4. Feature flag `USE_AGENT_TASK_QUEUE=0` reverts to synchronous direct send
  5. HITL gate: send_email defaults to requires_approval=True; send_whatsapp doesn't

The send executor itself is tested via stubs since actually firing SMTP /
Twilio in a unit test is out of scope. Integration-level end-to-end comes
in Week 2.4.
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import sys
import types

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import AgentTask, utc_now


# Fixtures

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


@pytest.fixture(autouse=True)
def _queue_on(monkeypatch):
    """Default for every test: queue is enabled. Individual tests can override."""
    monkeypatch.setenv("USE_AGENT_TASK_QUEUE", "1")


# Import after env is set and sys.path is configured by conftest
from services.agent.dispatch_service import (
    _build_idempotency_key,
    enqueue_send_email,
    enqueue_send_quote,
    enqueue_send_whatsapp,
)


# Invariant 1: queue path creates an AgentTask

class TestEnqueueShape:
    def test_send_email_creates_task(self, session):
        task = enqueue_send_email(
            session,
            company_id=1, lead_id=42, actor_user_id=7,
            subject="Quote attached", body="Hi there",
            trigger="ism_stage:engaged",
        )
        assert task.task_type == "send_email"
        assert task.assigned_agent == "send"
        assert task.company_id == 1
        assert task.lead_id == 42
        assert task.input_json["subject"] == "Quote attached"
        assert task.input_json["body"] == "Hi there"
        assert task.input_json["task_type"] == "send_email"
        # Summary is set for the approval UI
        assert "42" in task.input_json["summary"]

    def test_send_whatsapp_creates_task(self, session):
        task = enqueue_send_whatsapp(
            session,
            company_id=1, lead_id=7, actor_user_id=3,
            body="Hey are you free tomorrow?",
            trigger="manual",
        )
        assert task.task_type == "send_whatsapp"
        assert task.input_json["body"] == "Hey are you free tomorrow?"
        assert task.assigned_agent == "send"

    def test_send_quote_creates_task(self, session):
        task = enqueue_send_quote(
            session,
            company_id=1, lead_id=9, actor_user_id=3,
            quote_id=100, channels=["email", "whatsapp"],
            subject="Your quote", message="attached",
            trigger="ism_stage:quote_sent",
        )
        assert task.task_type == "send_quote"
        assert task.input_json["quote_id"] == 100
        assert task.input_json["channels"] == ["email", "whatsapp"]


# Invariant 2 + 3: idempotency key dedup behavior

class TestIdempotencyDedup:
    def test_duplicate_enqueue_dedupes(self, session):
        first = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hello", body="body",
            trigger="ism_stage:engaged",
        )
        second = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hello", body="body",
            trigger="ism_stage:engaged",
        )
        assert first.id == second.id, "Same (lead, trigger, subject) must dedupe"
        rows = session.exec(select(AgentTask)).all()
        assert len(rows) == 1

    def test_different_subject_creates_new_task(self, session):
        a = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hello", body="body", trigger="manual",
        )
        b = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Follow up", body="body", trigger="manual",
        )
        assert a.id != b.id

    def test_different_trigger_creates_new_task(self, session):
        a = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hello", body="body", trigger="campaign:welcome_1",
        )
        b = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hello", body="body", trigger="campaign:welcome_2",
        )
        assert a.id != b.id

    def test_different_lead_creates_new_task(self, session):
        a = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hello", body="body", trigger="manual",
        )
        b = enqueue_send_email(
            session, company_id=1, lead_id=43, actor_user_id=7,
            subject="Hello", body="body", trigger="manual",
        )
        assert a.id != b.id

    def test_idempotency_key_is_deterministic(self):
        """Same inputs → same hash, regardless of when or where generated."""
        k1 = _build_idempotency_key("send_email", 42, "manual", "Hello")
        k2 = _build_idempotency_key("send_email", 42, "manual", "Hello")
        assert k1 == k2

    def test_idempotency_key_length_fits_column(self):
        """AgentTask.idempotency_key is VARCHAR(200); our keys must fit comfortably."""
        # Unreasonably long inputs shouldn't overflow — hash caps the tail
        key = _build_idempotency_key("send_email", 42, "trigger" * 100, "subject" * 100)
        assert len(key) <= 200


# Invariant 4: feature flag rollback

class TestFeatureFlag:
    def test_flag_off_calls_service_directly(self, session, monkeypatch):
        """USE_AGENT_TASK_QUEUE=0 must bypass the queue and call the sender synchronously."""
        monkeypatch.setenv("USE_AGENT_TASK_QUEUE", "0")

        # Stub the underlying sender so we don't need a real Lead + network.
        called = []

        def stub_send_email(**kwargs):
            called.append(kwargs)
            return {"stubbed": True}

        stub_mod = types.ModuleType("services.communication.communication_service")
        stub_mod.send_email_to_lead = stub_send_email
        monkeypatch.setitem(sys.modules, "services.communication.communication_service", stub_mod)

        result = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hi", body="x", trigger="manual",
        )

        # No AgentTask created (queue off)
        tasks = session.exec(select(AgentTask)).all()
        assert len(tasks) == 0
        # Underlying sender was called once with the right shape
        assert len(called) == 1
        assert called[0]["lead_id"] == 42
        assert called[0]["subject"] == "Hi"
        assert result == {"stubbed": True}

    def test_flag_on_does_not_call_service(self, session, monkeypatch):
        """Queue on: underlying sender must NOT be called — executor handles it later."""
        called = []
        stub_mod = types.ModuleType("services.communication.communication_service")
        stub_mod.send_email_to_lead = lambda **kw: called.append(kw)
        monkeypatch.setitem(sys.modules, "services.communication.communication_service", stub_mod)

        enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hi", body="x",
        )
        assert called == [], "Queue path must NOT call the sender — that's the executor's job"

        # But the AgentTask IS created
        tasks = session.exec(select(AgentTask)).all()
        assert len(tasks) == 1


# Invariant 5: HITL gate defaults

class TestApprovalDefaults:
    def test_send_email_requires_approval_by_default(self, session):
        """send_email is in _DEFAULT_APPROVAL_REQUIRED — must land as requires_approval=True."""
        task = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Hi", body="x",
        )
        assert task.requires_approval is True

    def test_send_whatsapp_single_does_not_require_approval(self, session):
        """send_whatsapp (single) is NOT in default approval set — send_whatsapp_BULK is."""
        task = enqueue_send_whatsapp(
            session, company_id=1, lead_id=42, actor_user_id=7,
            body="Quick check",
        )
        assert task.requires_approval is False

    def test_send_quote_requires_approval_by_default(self, session):
        """send_quote is in _DEFAULT_APPROVAL_REQUIRED."""
        task = enqueue_send_quote(
            session, company_id=1, lead_id=42, actor_user_id=7,
            quote_id=100, channels=["email"],
        )
        assert task.requires_approval is True

    def test_caller_can_override_approval(self, session):
        """Trusted callers can bypass the default by passing requires_approval=False."""
        task = enqueue_send_email(
            session, company_id=1, lead_id=42, actor_user_id=7,
            subject="Automated follow-up", body="x",
            requires_approval=False,
        )
        assert task.requires_approval is False


# Bonus: send executor dispatches to the right handler

class TestSendExecutorDispatch:
    """Smoke tests for agents/send.py::run — doesn't actually fire SMTP/Twilio,
    just verifies the right handler is picked and payload shape is right."""

    @pytest.mark.asyncio
    async def test_unknown_task_type_returns_error(self):
        from agents.send import run
        result = await run(company_id=1, actor_user_id=1, lead_id=1, task_type="nonsense")
        assert result["ok"] is False
        assert "unknown task_type" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_task_type_returns_error(self):
        from agents.send import run
        result = await run(company_id=1, actor_user_id=1, lead_id=1)
        assert result["ok"] is False
        assert "without task_type" in result["error"]

    @pytest.mark.asyncio
    async def test_send_quote_without_quote_id_returns_error(self, monkeypatch):
        from agents.send import run

        # Stub send_quote_to_lead so we verify the pre-check fires before calling it
        called = []
        stub_mod = types.ModuleType("services.communication.communication_service")
        stub_mod.send_quote_to_lead = lambda **kw: called.append(kw)
        monkeypatch.setitem(sys.modules, "services.communication.communication_service", stub_mod)

        result = await run(company_id=1, actor_user_id=1, lead_id=1, task_type="send_quote")
        assert result["ok"] is False
        assert "quote_id" in result["error"]
        assert called == [], "pre-check must fire before touching the sender"
