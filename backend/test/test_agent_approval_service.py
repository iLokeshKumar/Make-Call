"""Invariant tests for Week 3.1c — agent_approval_service.

The approval queue is the HITL safety rail. If any of these break, the
agent can execute tasks without human review. Load-bearing invariants:

  1. create_approval is idempotent — one pending approval per task
  2. approve() flips task.status='pending' + requires_approval=False so the
     worker picks it up without re-triggering the approval gate
  3. reject() marks task.status='rejected' (terminal) — never retried
  4. approve/reject require a pending approval row — errors if missing
  5. get_pending filters correctly by company + status='pending'
  6. expire_stale() only expires past-deadline rows; others untouched
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from models.models import AgentApproval, AgentTask, utc_now
from services.agent.agent_approval_service import (
    approve,
    create_approval,
    expire_stale,
    get_pending,
    reject,
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


def _seed_task(session, **overrides) -> AgentTask:
    defaults = {
        "company_id": 1,
        "task_type": "send_email",
        "assigned_agent": "send",
        "status": "awaiting_approval",
        "input_json": {"subject": "test", "body": "x", "task_type": "send_email"},
        "requires_approval": True,
    }
    defaults.update(overrides)
    task = AgentTask(**defaults)
    session.add(task); session.commit(); session.refresh(task)
    return task


# create_approval idempotency

class TestCreateApprovalIdempotent:
    def test_duplicate_create_returns_same_row(self, session):
        task = _seed_task(session)
        first = create_approval(
            session, company_id=1, task_id=task.id,
            action_type="send_email", action_summary="Send email to X",
            action_payload={"subject": "hi"},
        )
        second = create_approval(
            session, company_id=1, task_id=task.id,
            action_type="send_email", action_summary="Duplicate attempt",
            action_payload={"different": "payload"},
        )
        assert first.id == second.id
        # Only one row exists
        rows = session.exec(select(AgentApproval)).all()
        assert len(rows) == 1

    def test_new_task_gets_new_approval(self, session):
        t1 = _seed_task(session)
        t2 = _seed_task(session)
        a1 = create_approval(session, company_id=1, task_id=t1.id,
                             action_type="x", action_summary="s", action_payload={})
        a2 = create_approval(session, company_id=1, task_id=t2.id,
                             action_type="x", action_summary="s", action_payload={})
        assert a1.id != a2.id


# approve()

class TestApprove:
    def test_approve_flips_task_to_pending(self, session):
        task = _seed_task(session, status="awaiting_approval")
        create_approval(session, company_id=1, task_id=task.id,
                        action_type="send_email", action_summary="s", action_payload={})
        approve(session, company_id=1, task_id=task.id, reviewer_id=99, note="ok")

        session.refresh(task)
        assert task.status == "pending"
        assert task.requires_approval is False, \
            "Worker must not re-gate an approved task"

    def test_approve_records_reviewer_and_note(self, session):
        task = _seed_task(session)
        appr = create_approval(session, company_id=1, task_id=task.id,
                               action_type="send_email", action_summary="s", action_payload={})
        approve(session, company_id=1, task_id=task.id, reviewer_id=42, note="looks good")

        session.refresh(appr)
        assert appr.status == "approved"
        assert appr.reviewer_id == 42
        assert appr.reviewer_note == "looks good"
        assert appr.reviewed_at is not None

    def test_approve_without_pending_approval_raises(self, session):
        task = _seed_task(session, status="pending", requires_approval=False)
        # No approval row exists for this task
        with pytest.raises(HTTPException) as exc_info:
            approve(session, company_id=1, task_id=task.id, reviewer_id=1, note=None)
        assert exc_info.value.status_code == 400

    def test_approve_missing_task_raises_404(self, session):
        with pytest.raises(HTTPException) as exc_info:
            approve(session, company_id=1, task_id=99999, reviewer_id=1, note=None)
        assert exc_info.value.status_code == 404

    def test_approve_respects_company_isolation(self, session):
        """A company cannot approve another company's task."""
        task = _seed_task(session, company_id=1)
        create_approval(session, company_id=1, task_id=task.id,
                        action_type="x", action_summary="s", action_payload={})
        with pytest.raises(HTTPException) as exc_info:
            approve(session, company_id=2, task_id=task.id, reviewer_id=1, note=None)
        assert exc_info.value.status_code == 404


# reject()

class TestReject:
    def test_reject_flips_task_to_rejected(self, session):
        task = _seed_task(session)
        create_approval(session, company_id=1, task_id=task.id,
                        action_type="x", action_summary="s", action_payload={})
        reject(session, company_id=1, task_id=task.id, reviewer_id=7, note="not appropriate")

        session.refresh(task)
        assert task.status == "rejected"
        assert task.completed_at is not None
        assert task.error_json["rejected_by"] == 7
        assert task.error_json["note"] == "not appropriate"

    def test_reject_records_approval_reviewer(self, session):
        task = _seed_task(session)
        appr = create_approval(session, company_id=1, task_id=task.id,
                               action_type="x", action_summary="s", action_payload={})
        reject(session, company_id=1, task_id=task.id, reviewer_id=99, note="no")

        session.refresh(appr)
        assert appr.status == "rejected"
        assert appr.reviewer_id == 99
        assert appr.reviewer_note == "no"


# get_pending

class TestGetPending:
    def test_returns_only_pending_approvals(self, session):
        t1 = _seed_task(session)
        t2 = _seed_task(session)
        t3 = _seed_task(session)
        create_approval(session, 1, t1.id, "x", "first", {})
        a2 = create_approval(session, 1, t2.id, "x", "second", {})
        create_approval(session, 1, t3.id, "x", "third", {})

        # Reject one — shouldn't appear in pending list
        reject(session, 1, t2.id, reviewer_id=1, note="no")

        pending = get_pending(session, company_id=1)
        pending_task_ids = {p["task_id"] for p in pending}
        assert t1.id in pending_task_ids
        assert t2.id not in pending_task_ids  # rejected
        assert t3.id in pending_task_ids

    def test_filters_by_company(self, session):
        t_mine = _seed_task(session, company_id=1)
        t_theirs = _seed_task(session, company_id=2)
        create_approval(session, 1, t_mine.id, "x", "mine", {})
        create_approval(session, 2, t_theirs.id, "x", "theirs", {})

        # Company 1 sees only their own
        pending_1 = get_pending(session, company_id=1)
        assert len(pending_1) == 1
        assert pending_1[0]["task_id"] == t_mine.id

        # Company 2 sees only theirs
        pending_2 = get_pending(session, company_id=2)
        assert len(pending_2) == 1
        assert pending_2[0]["task_id"] == t_theirs.id

    def test_includes_linked_task_metadata(self, session):
        task = _seed_task(session, task_type="send_quote", lead_id=42, priority=3)
        create_approval(session, 1, task.id, "send_quote", "s", {})

        pending = get_pending(session, company_id=1)
        assert pending[0]["task"]["task_type"] == "send_quote"
        assert pending[0]["task"]["lead_id"] == 42
        assert pending[0]["task"]["priority"] == 3


# expire_stale

class TestExpireStale:
    def test_expires_past_deadline_approvals(self, session):
        task = _seed_task(session)
        appr = create_approval(
            session, 1, task.id, "x", "s", {},
            expires_in_hours=1,
        )
        # Backdate the expires_at so it's in the past
        appr.expires_at = utc_now() - timedelta(hours=2)
        session.add(appr); session.commit()

        count = expire_stale(session, company_id=1)
        assert count == 1

        session.refresh(appr)
        assert appr.status == "expired"

        session.refresh(task)
        assert task.status == "rejected"
        assert task.error_json["reason"] == "approval_expired"

    def test_ignores_fresh_approvals(self, session):
        task = _seed_task(session)
        create_approval(session, 1, task.id, "x", "s", {}, expires_in_hours=24)

        count = expire_stale(session, company_id=1)
        assert count == 0

    def test_only_touches_specified_company(self, session):
        t1 = _seed_task(session, company_id=1)
        t2 = _seed_task(session, company_id=2)
        a1 = create_approval(session, 1, t1.id, "x", "s", {}, expires_in_hours=1)
        a2 = create_approval(session, 2, t2.id, "x", "s", {}, expires_in_hours=1)
        # Both expired
        a1.expires_at = utc_now() - timedelta(hours=2)
        a2.expires_at = utc_now() - timedelta(hours=2)
        session.add(a1); session.add(a2); session.commit()

        # Only expire company 1's
        count = expire_stale(session, company_id=1)
        assert count == 1

        session.refresh(a1); session.refresh(a2)
        assert a1.status == "expired"
        assert a2.status == "pending"   # untouched
