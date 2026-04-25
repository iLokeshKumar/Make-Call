"""
Agent Tasks API — task bus and human approval queue for the multi-agent orchestrator.

Endpoints:
  GET  /agent-tasks                    — list tasks (filterable)
  POST /agent-tasks                    — create task manually
  GET  /agent-tasks/approvals          — pending approval queue
  GET  /agent-tasks/{id}               — task detail + linked approval
  POST /agent-tasks/{id}/cancel        — cancel a pending task
  POST /agent-tasks/{id}/approve       — approve an action (reviewer)
  POST /agent-tasks/{id}/reject        — reject an action (reviewer)
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import AgentApproval, AgentTask, User, utc_now
from services.agent.agent_task_service import create_agent_task
from services.agent.agent_approval_service import (
    approve,
    expire_stale,
    get_pending,
    reject,
)
from services.agent.approval_presenter import present

router = APIRouter(prefix="/agent-tasks", tags=["Agent Tasks"])


# Request models

class CreateTaskRequest(BaseModel):
    task_type: str
    assigned_agent: str
    input_json: dict[str, Any] = {}
    lead_id: Optional[int] = None
    requires_approval: Optional[bool] = None
    priority: int = 5
    idempotency_key: Optional[str] = None


class ApproveRequest(BaseModel):
    note: Optional[str] = None


class RejectRequest(BaseModel):
    note: str



@router.get("")
async def list_agent_tasks(
    status: Optional[str] = Query(default=None, description="Filter by status"),
    assigned_agent: Optional[str] = Query(default=None),
    lead_id: Optional[int] = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """List agent tasks for this company, optionally filtered."""
    query = select(AgentTask).where(AgentTask.company_id == current_user.company_id)
    if status:
        query = query.where(AgentTask.status == status)
    if assigned_agent:
        query = query.where(AgentTask.assigned_agent == assigned_agent)
    if lead_id is not None:
        query = query.where(AgentTask.lead_id == lead_id)
    query = query.order_by(AgentTask.created_at.desc()).offset(skip).limit(limit)
    return session.exec(query).all()


@router.post("")
async def create_task(
    body: CreateTaskRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Manually enqueue an agent task."""
    return create_agent_task(
        session=session,
        company_id=current_user.company_id,
        task_type=body.task_type,
        assigned_agent=body.assigned_agent,
        input_json=body.input_json,
        lead_id=body.lead_id,
        requires_approval=body.requires_approval,
        priority=body.priority,
        idempotency_key=body.idempotency_key,
        actor_user_id=current_user.id,
    )


@router.get("/approvals")
async def list_pending_approvals(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Return all actions currently awaiting human approval.

    Each item includes a `presentation` field produced by approval_presenter
    with human-readable title/description/preview/warnings. The original
    `action_payload` is preserved under that key for power-user access.
    """
    # Expire stale approvals first so the list is always fresh
    expire_stale(session=session, company_id=current_user.company_id)
    items = get_pending(session=session, company_id=current_user.company_id, skip=skip, limit=limit)

    # Enrich each approval with a presenter-rendered view. The presenter is pure + defensive — never raises — so this is safe inline.
    task_type_for = {
        it["task_id"]: (it.get("task") or {}).get("task_type") or it.get("action_type")
        for it in items
    }
    for it in items:
        tt = task_type_for.get(it["task_id"]) or it.get("action_type") or ""
        lead_id = (it.get("task") or {}).get("lead_id")
        it["presentation"] = present(
            task_type=tt,
            input_json=it.get("action_payload") or {},
            company_id=current_user.company_id,
            lead_id=lead_id,
            session=session,
        )
    return items


@router.get("/{task_id}")
async def get_task(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Get a single task with its linked approval (if any)."""
    task = session.exec(
        select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.company_id == current_user.company_id,
        )
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found")

    approval = session.exec(
        select(AgentApproval).where(AgentApproval.task_id == task_id)
        .order_by(AgentApproval.created_at.desc())
    ).first()

    return {
        "task": task,
        "approval": approval,
    }


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Cancel a pending or awaiting-approval task."""
    task = session.exec(
        select(AgentTask).where(
            AgentTask.id == task_id,
            AgentTask.company_id == current_user.company_id,
        )
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Agent task not found")
    if task.status not in ("pending", "awaiting_approval"):
        raise HTTPException(status_code=400, detail=f"Cannot cancel task in status '{task.status}'")

    task.status = "rejected"
    task.completed_at = utc_now()
    task.error_json = {"reason": "cancelled_by_user", "user_id": current_user.id}
    task.updated_at = utc_now()
    task.updated_by = current_user.id
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


# Approval endpoints

@router.post("/{task_id}/approve")
async def approve_task(
    task_id: int,
    body: ApproveRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Approve a pending agent action — re-queues it for execution."""
    return approve(
        session=session,
        company_id=current_user.company_id,
        task_id=task_id,
        reviewer_id=current_user.id,
        note=body.note,
    )


@router.post("/{task_id}/reject")
async def reject_task(
    task_id: int,
    body: RejectRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """Reject a pending agent action — marks it as rejected (not retried)."""
    return reject(
        session=session,
        company_id=current_user.company_id,
        task_id=task_id,
        reviewer_id=current_user.id,
        note=body.note,
    )
