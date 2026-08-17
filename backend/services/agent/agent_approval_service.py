"""
Agent Approval Service — human-in-the-loop review queue.

When an agent produces a high-stakes task (send_email, send_quote, etc.)
the task is parked with status='awaiting_approval' and an AgentApproval record
is created. Operators approve or reject via the portal (/agent-tasks).

After approval the task's status returns to 'pending' so the worker picks it
up on the next cycle and executes it without re-checking approval.

After rejection the task is marked 'rejected' (terminal — not retried).

Stale approvals past expires_at are auto-rejected by expire_stale() which
the worker calls once per cycle.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import AgentApproval, AgentTask, utc_now

logger = logging.getLogger(__name__)

_DEFAULT_EXPIRY_HOURS = 24


def create_approval(
    session: Session,
    company_id: int,
    task_id: int,
    action_type: str,
    action_summary: str,
    action_payload: dict[str, Any],
    *,
    expires_in_hours: int = _DEFAULT_EXPIRY_HOURS,
    actor_user_id: int | None = None,
) -> AgentApproval:
    """Create an approval request linked to an agent task."""
    existing = session.exec(
        select(AgentApproval).where(
            AgentApproval.task_id == task_id,
            AgentApproval.status == "pending",
        )
    ).first()
    if existing:
        return existing

    approval = AgentApproval(
        company_id=company_id,
        task_id=task_id,
        action_type=action_type,
        action_summary=action_summary,
        action_payload=action_payload,
        status="pending",
        expires_at=utc_now() + timedelta(hours=expires_in_hours),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(approval)
    session.commit()
    session.refresh(approval)
    logger.info(
        "[AgentApproval] Created approval id=%s for task=%s type=%s",
        approval.id, task_id, action_type,
    )
    return approval


def _get_approval_and_task(
    session: Session,
    company_id: int,
    task_id: int,
) -> tuple[AgentApproval, AgentTask]:
    """Fetch the pending approval + task; raise 404/400 on invalid state."""
    task = session.exec(
        select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.company_id == company_id,
        )
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found")

    approval = session.exec(
        select(AgentApproval).where(
            AgentApproval.task_id == task_id,
            AgentApproval.status == "pending",
        )
    ).first()
    if not approval:
        raise HTTPException(
            status_code=400,
            detail=f"No pending approval for task {task_id} (status: {task.status})",
        )
    return approval, task


def approve(
    session: Session,
    company_id: int,
    task_id: int,
    reviewer_id: int,
    note: str | None = None,
) -> AgentApproval:
    """
    Approve the pending approval for a task.
    Sets approval.status=approved, task.status=pending (worker picks it up next cycle).
    """
    approval, task = _get_approval_and_task(session, company_id, task_id)

    now = utc_now()
    approval.status = "approved"
    approval.reviewer_id = reviewer_id
    approval.reviewed_at = now
    approval.reviewer_note = note
    approval.updated_at = now
    approval.updated_by = reviewer_id
    session.add(approval)

    task.status = "pending"   # re-queued for the worker; approval gate won't re-fire
    task.requires_approval = False  # cleared so worker doesn't re-gate it
    task.updated_at = now
    task.updated_by = reviewer_id
    session.add(task)

    session.commit()
    session.refresh(approval)
    logger.info("[AgentApproval] Approved: approval=%s task=%s by user=%s", approval.id, task_id, reviewer_id)
    return approval


def reject(
    session: Session,
    company_id: int,
    task_id: int,
    reviewer_id: int,
    note: str,
) -> AgentApproval:
    """
    Reject the pending approval for a task.
    Sets approval.status=rejected, task.status=rejected (terminal).
    """
    approval, task = _get_approval_and_task(session, company_id, task_id)

    now = utc_now()
    approval.status = "rejected"
    approval.reviewer_id = reviewer_id
    approval.reviewed_at = now
    approval.reviewer_note = note
    approval.updated_at = now
    approval.updated_by = reviewer_id
    session.add(approval)

    task.status = "rejected"
    task.completed_at = now
    task.error_json = {"rejected_by": reviewer_id, "note": note}
    task.updated_at = now
    task.updated_by = reviewer_id
    session.add(task)

    session.commit()
    session.refresh(approval)
    logger.info("[AgentApproval] Rejected: approval=%s task=%s by user=%s", approval.id, task_id, reviewer_id)
    return approval


def get_pending(
    session: Session,
    company_id: int,
    skip: int = 0,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return pending approvals with their linked task details."""
    approvals = session.exec(
        select(AgentApproval).where(
            AgentApproval.company_id == company_id,
            AgentApproval.status == "pending",
        ).order_by(AgentApproval.created_at.asc()).offset(skip).limit(limit)
    ).all()

    results = []
    for appr in approvals:
        task = session.get(AgentTask, appr.task_id)
        results.append({
            "approval_id": appr.id,
            "task_id": appr.task_id,
            "action_type": appr.action_type,
            "action_summary": appr.action_summary,
            "action_payload": appr.action_payload,
            "status": appr.status,
            "expires_at": appr.expires_at.isoformat() if appr.expires_at else None,
            "created_at": appr.created_at.isoformat(),
            "task": {
                "task_type": task.task_type if task else None,
                "assigned_agent": task.assigned_agent if task else None,
                "lead_id": task.lead_id if task else None,
                "priority": task.priority if task else None,
            },
        })
    return results


def expire_and_escalate_approvals(session: Session, company_id: int) -> dict:
    """
    Expire and escalate approvals in a single pass.

    - Expired: pending approvals whose expires_at < utc_now().
      Sets status='expired', linked AgentTask status='rejected'.

    - Escalated: pending approvals not yet expired but past SLA
      (created_at + 24h < utc_now()).  These get '[ESCALATED]' prepended to
      reviewer_note so they surface prominently in the approval queue.

    Returns {"expired": <count>, "escalated": <count>}.
    """
    now = utc_now()
    sla_threshold = now - timedelta(hours=24)

    # ── 1. Expire past-deadline approvals ────────────────────────────────────
    stale = session.exec(
        select(AgentApproval).where(
            AgentApproval.company_id == company_id,
            AgentApproval.status == "pending",
            AgentApproval.expires_at <= now,
        )
    ).all()

    expired_count = 0
    for appr in stale:
        appr.status = "expired"
        appr.updated_at = now
        session.add(appr)

        task = session.get(AgentTask, appr.task_id)
        if task and task.status == "awaiting_approval":
            # Keep terminal semantics consistent with manual rejects
            task.status = "rejected"
            task.completed_at = now
            task.error_json = {"reason": "approval_expired"}
            task.updated_at = now
            session.add(task)

        expired_count += 1

    if expired_count:
        session.commit()
        logger.info(
            "[AgentApproval] Expired %d stale approvals for company %s",
            expired_count, company_id,
        )

    # ── 2. Escalate past-SLA approvals that are not yet expired ─────────────
    past_sla = session.exec(
        select(AgentApproval).where(
            AgentApproval.company_id == company_id,
            AgentApproval.status == "pending",
            AgentApproval.expires_at > now,       # not yet expired
            AgentApproval.created_at <= sla_threshold,  # created > 24h ago
        )
    ).all()

    escalated_count = 0
    for appr in past_sla:
        existing_note = appr.reviewer_note or ""
        if not existing_note.startswith("[ESCALATED]"):
            appr.reviewer_note = f"[ESCALATED] {existing_note}".strip()
            appr.updated_at = now
            session.add(appr)
            escalated_count += 1

    if escalated_count:
        session.commit()
        logger.info(
            "[AgentApproval] Escalated %d past-SLA approvals for company %s",
            escalated_count, company_id,
        )

    return {"expired": expired_count, "escalated": escalated_count}


def expire_stale(session: Session, company_id: int) -> int:
    """
    Auto-expire approvals past their expires_at deadline.
    Called by the automation worker once per cycle.
    Returns the count of approvals expired.

    Delegates to expire_and_escalate_approvals() for combined expiry + SLA escalation.
    """
    result = expire_and_escalate_approvals(session=session, company_id=company_id)
    return result["expired"]
