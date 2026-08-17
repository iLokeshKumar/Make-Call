"""Invariant tests for the AgentTask durable queue.

These lock down the load-bearing guarantees of the autonomous agent layer.
Every property tested here is something that, if broken, would cause the
agent to either skip work, double-execute work, or execute work that should
have been gated by human approval.

The five invariants:
  1. Idempotency: same key → same row, never two
  2. Backoff: failures wait [2, 10, 30] minutes between retries
  3. Approval gate: requires_approval=True parks the task, never executes
  4. Terminal failure: attempts == max_attempts → status='failed', no retry
  5. Default approval set: send_email / send_quote / send_whatsapp_bulk gated

Uses in-memory SQLite so DB-level UQ enforcement is real, not mocked.
Postgres-only features (pg_advisory_lock, FOR UPDATE SKIP LOCKED) are out
of scope here — the company-level advisory lock pattern lives in the worker
loop and is a different test surface.
"""
from __future__ import annotations

import os

# Suppress the per-session "no rls_company_id" warning that database.py emits.
# Our tests don't go through HTTP middleware so we never set the ContextVar.
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import sys
import types
from datetime import datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select


def _naive_utc_now() -> datetime:
    """SQLite strips tzinfo on roundtrip — compare naive-vs-naive in tests.

    Production runs on Postgres with `DateTime(timezone=True)` which preserves
    the offset, so this shim is test-only.
    """
    return utc_now().replace(tzinfo=None)

from models.models import AgentTask, utc_now
from services.agent.agent_task_service import (
    _DEFAULT_APPROVAL_REQUIRED,
    _backoff_minutes,
    action_requires_approval,
    create_agent_task,
    fail_task,
    run_agent_tasks,
)


# Fixtures

@pytest.fixture
def engine():
    """One in-memory SQLite engine per test, shared across sessions via StaticPool.

    StaticPool keeps a single connection so all sessions in the test see the
    same in-memory database (otherwise each connection gets its own ":memory:").
    """
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


# Invariant 1: idempotency_key dedup

class TestIdempotencyDedup:
    def test_repeated_create_returns_same_task(self, session):
        first = create_agent_task(
            session, company_id=1, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={"lead_id": 42},
            idempotency_key="webhook:abc-123",
            requires_approval=False,
        )
        second = create_agent_task(
            session, company_id=1, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={"lead_id": 42},
            idempotency_key="webhook:abc-123",
            requires_approval=False,
        )
        assert second.id == first.id, "Same idempotency_key must return existing row"

        all_rows = session.exec(select(AgentTask)).all()
        assert len(all_rows) == 1, "Dedup must not insert a second row"

    def test_different_keys_create_different_tasks(self, session):
        a = create_agent_task(
            session, company_id=1, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={},
            idempotency_key="key-a", requires_approval=False,
        )
        b = create_agent_task(
            session, company_id=1, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={},
            idempotency_key="key-b", requires_approval=False,
        )
        assert a.id != b.id


# Invariant 2: backoff schedule [2, 10, 30] minutes

class TestBackoffSchedule:
    """The retry delay schedule lives in agent_task_service._RETRY_DELAYS_MINUTES.

    These tests pin the exact sequence so a refactor can't silently change it
    (e.g., flipping to [1, 2, 4] would break customer-facing SLAs).
    """

    def test_first_retry_waits_2_minutes(self):
        assert _backoff_minutes(0) == 2

    def test_second_retry_waits_10_minutes(self):
        assert _backoff_minutes(1) == 10

    def test_third_retry_waits_30_minutes(self):
        assert _backoff_minutes(2) == 30

    def test_overflow_clamps_to_last(self):
        # Even at attempt 99 we should not crash — clamp to the longest delay
        assert _backoff_minutes(99) == 30

    def test_negative_clamps_to_first(self):
        # Defensive: a negative attempt should not index off the front of the list
        assert _backoff_minutes(-1) == 2

    def test_fail_task_writes_run_after_with_backoff(self, session):
        """End-to-end: fail_task on a non-terminal task sets run_after = now + delay."""
        task = create_agent_task(
            session, company_id=1, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={},
            idempotency_key="backoff-1", requires_approval=False,
        )
        task.attempts = 1  # simulate one prior claim_task increment
        task.max_attempts = 3
        session.add(task); session.commit()

        before = _naive_utc_now()
        fail_task(session, task, "transient error")

        assert task.status == "pending", "Should re-queue, not fail terminally"
        run_after = task.run_after.replace(tzinfo=None) if task.run_after.tzinfo else task.run_after
        delta = run_after - before
        # _backoff_minutes(0) == 2 minutes; allow 1-3 min window for clock skew
        assert timedelta(minutes=1) <= delta <= timedelta(minutes=3)


# Invariant 3: approval gate

class TestAwaitingApprovalGate:
    """A task with requires_approval=True must be parked, never executed.

    This is the load-bearing guarantee of the HITL system. If this breaks,
    the agent could send unapproved emails / quotes / bulk WhatsApp.
    """

    def test_approval_required_task_never_executes(self, session, monkeypatch):
        # Stub the lazily-imported create_approval so we don't pull in
        # the full credentials_service dependency chain.
        approval_calls = []

        def stub_create_approval(**kwargs):
            approval_calls.append(kwargs)

        stub_approval = types.ModuleType("services.agent.agent_approval_service")
        stub_approval.create_approval = stub_create_approval
        monkeypatch.setitem(sys.modules, "services.agent.agent_approval_service", stub_approval)

        # Stub the orchestrator so if we DID accidentally execute, we'd notice.
        execution_calls = []

        async def stub_run_agent(**kwargs):
            execution_calls.append(kwargs)
            return {"ok": True}

        # The lazy import is `from agents.orchestrator import run_agent` — we
        # need both `agents` package and `agents.orchestrator` module to exist
        # in sys.modules before the import resolves.
        stub_agents_pkg = types.ModuleType("agents")
        stub_orch = types.ModuleType("agents.orchestrator")
        stub_orch.run_agent = stub_run_agent
        stub_agents_pkg.orchestrator = stub_orch
        monkeypatch.setitem(sys.modules, "agents", stub_agents_pkg)
        monkeypatch.setitem(sys.modules, "agents.orchestrator", stub_orch)

        task = create_agent_task(
            session, company_id=1, task_type="send_email",
            assigned_agent="campaign", input_json={"summary": "follow-up"},
            idempotency_key="approve-1",
            requires_approval=True,
        )

        result = run_agent_tasks(session, company_id=1, actor_user_id=1, limit=10)

        assert result["queued_for_approval"] == 1
        assert result["done"] == 0
        assert result["failed"] == 0

        session.refresh(task)
        assert task.status == "awaiting_approval"
        assert execution_calls == [], "Orchestrator must NOT be invoked for unapproved tasks"
        assert len(approval_calls) == 1
        assert approval_calls[0]["task_id"] == task.id


# Invariant 4: terminal failure after max_attempts

class TestMaxAttemptsTerminal:
    """fail_task re-queues until attempts == max_attempts, then marks 'failed'.

    A 'failed' task must not be picked up again by the worker. This is what
    eventually fires the dead-letter alert (automation_worker_service:482).
    """

    def _seed(self, session, max_attempts: int) -> AgentTask:
        task = create_agent_task(
            session, company_id=1, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={},
            idempotency_key=f"max-{max_attempts}-{utc_now().timestamp()}",
            requires_approval=False,
        )
        task.max_attempts = max_attempts
        session.add(task); session.commit(); session.refresh(task)
        return task

    def test_attempts_below_max_is_pending(self, session):
        task = self._seed(session, max_attempts=3)
        task.attempts = 1
        session.add(task); session.commit()

        fail_task(session, task, "transient")

        assert task.status == "pending"
        run_after = task.run_after.replace(tzinfo=None) if task.run_after.tzinfo else task.run_after
        assert run_after > _naive_utc_now()

    def test_attempts_at_max_marks_failed(self, session):
        task = self._seed(session, max_attempts=3)
        task.attempts = 3  # already used all attempts
        session.add(task); session.commit()

        fail_task(session, task, "permanent error")

        assert task.status == "failed"
        assert task.completed_at is not None

    def test_failed_state_persists_across_session(self, session, engine):
        """Reload from a fresh session — terminal state must be durable."""
        task = self._seed(session, max_attempts=1)
        task.attempts = 1
        session.add(task); session.commit()
        fail_task(session, task, "boom")
        task_id = task.id

        # New session, same in-memory DB
        with Session(engine) as fresh:
            reloaded = fresh.exec(select(AgentTask).where(AgentTask.id == task_id)).first()
            assert reloaded is not None
            assert reloaded.status == "failed"
            assert reloaded.error_json["error"] == "boom"


# Bonus: NOTIFY no-op on sqlite

class TestNotifyGracefullyNoOpOnSqlite:
    """create_agent_task should NOT crash on engines without pg_notify.

    The notify_listener module detects sqlite via dialect.name and skips the
    pg_notify call. This test pins that contract so a refactor doesn't
    accidentally break test environments that use sqlite.
    """

    def test_create_succeeds_without_postgres(self, session):
        # Just calling create_agent_task is the test — if NOTIFY error wasn't
        # swallowed, this would raise.
        task = create_agent_task(
            session, company_id=99, task_type="enrich_lead",
            assigned_agent="enrichment", input_json={},
            idempotency_key="notify-noop", requires_approval=False,
        )
        assert task.id is not None
        assert task.status == "pending"


# Invariant 5: default approval-required action set

class TestApprovalDefaults:
    """The set of actions that need human approval by default.

    Adding a new high-stakes action (e.g., "schedule_meeting") should be a
    deliberate decision — append to _DEFAULT_APPROVAL_REQUIRED, then add a
    test row here so the choice is visible in code review.
    """

    def test_send_email_requires_approval(self):
        assert "send_email" in _DEFAULT_APPROVAL_REQUIRED

    def test_send_quote_requires_approval(self):
        assert "send_quote" in _DEFAULT_APPROVAL_REQUIRED

    def test_send_whatsapp_bulk_requires_approval(self):
        assert "send_whatsapp_bulk" in _DEFAULT_APPROVAL_REQUIRED

    def test_helper_returns_true_for_default_action(self, session):
        assert action_requires_approval(session, company_id=1, task_type="send_email") is True

    def test_helper_returns_false_for_internal_action(self, session):
        # Lead enrichment is internal — no human eyeballs needed
        assert action_requires_approval(session, company_id=1, task_type="enrich_lead") is False

    def test_helper_is_case_insensitive(self, session):
        assert action_requires_approval(session, company_id=1, task_type="SEND_EMAIL") is True
