from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import (
    BatchCallTaskCreate,
    CallOutcomeApplyRequest,
    CallTaskCreate,
    CallTaskStatusUpdate,
    LeadOptOutRequest,
    User,
)
from services.dialer_service import create_batch_call_tasks, opt_out_lead_from_calls, run_batch_dialer
from services.outcome_service import apply_call_outcome
from services.outbound_call_service import (
    complete_call_task,
    create_call_task,
    fail_call_task,
    list_call_tasks,
    queue_call_task,
    start_call_task,
)


router = APIRouter(prefix="/call-tasks", tags=["Call Tasks"])


@router.post("")
async def create_call_task_route(
    data: CallTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return create_call_task(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=data.lead_id,
        campaign_id=data.campaign_id,
        campaign_step_id=data.campaign_step_id,
        assigned_user_id=data.assigned_user_id,
        scheduled_at=data.scheduled_at,
        notes=data.notes,
    )


@router.post("/batch")
async def create_batch_call_tasks_route(
    data: BatchCallTaskCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return create_batch_call_tasks(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_ids=data.lead_ids,
        assigned_user_id=data.assigned_user_id,
        batch_id=data.batch_id,
        scheduled_at=data.scheduled_at,
        notes=data.notes,
        dialer_source=data.dialer_source,
    )


@router.post("/run-batch")
async def run_batch_dialer_route(
    limit: int = Query(default=20, ge=1, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return run_batch_dialer(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        limit=limit,
    )


@router.get("")
async def list_call_tasks_route(
    status: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.read")),
):
    # Sales reps only see tasks assigned to them; admins/owners see all
    scope_user_id = (
        current_user.id
        if getattr(current_user, "role", None) == "sales_representative"
        else None
    )
    return list_call_tasks(session, current_user.company_id, status=status, user_id=scope_user_id)


@router.post("/{task_id}/queue")
async def queue_call_task_route(
    task_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return queue_call_task(session, current_user.company_id, current_user.id, task_id)


@router.post("/{task_id}/start")
async def start_call_task_route(
    task_id: int,
    data: CallTaskStatusUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return start_call_task(
        session,
        current_user.company_id,
        current_user.id,
        task_id,
        interaction_id=data.interaction_id,
    )


@router.post("/{task_id}/complete")
async def complete_call_task_route(
    task_id: int,
    data: CallTaskStatusUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return complete_call_task(
        session,
        current_user.company_id,
        current_user.id,
        task_id,
        interaction_id=data.interaction_id,
        outcome=data.outcome,
    )


@router.post("/{task_id}/fail")
async def fail_call_task_route(
    task_id: int,
    data: CallTaskStatusUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return fail_call_task(
        session,
        current_user.company_id,
        current_user.id,
        task_id,
        interaction_id=data.interaction_id,
        outcome=data.outcome,
    )


@router.post("/{task_id}/apply-outcome")
async def apply_call_outcome_route(
    task_id: int,
    data: CallOutcomeApplyRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return apply_call_outcome(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        task_id=task_id,
        interaction_id=data.interaction_id,
        raw_status=data.raw_status,
        transcript=data.transcript,
    )


@router.post("/leads/{lead_id}/opt-out")
async def opt_out_calling_route(
    lead_id: int,
    data: LeadOptOutRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("call_task.manage")),
):
    return opt_out_lead_from_calls(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        lead_id=lead_id,
        reason=data.reason,
    )
