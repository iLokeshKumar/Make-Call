from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import CallTask, Lead, utc_now


def get_lead_or_404(session: Session, company_id: int, lead_id: int) -> Lead:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead


def get_call_task_or_404(session: Session, company_id: int, task_id: int) -> CallTask:
    task = session.exec(
        select(CallTask).where(
            CallTask.id == task_id,
            CallTask.company_id == company_id,
        )
    ).first()
    if not task:
        raise HTTPException(status_code=404, detail="Call task not found")
    return task


def create_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    campaign_id: Optional[int] = None,
    campaign_step_id: Optional[int] = None,
    assigned_user_id: Optional[int] = None,
    scheduled_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    campaign_recipient_id: Optional[int] = None,
    batch_id: Optional[str] = None,
    max_attempts: int = 3,
    dialer_source: Optional[str] = None,
    initial_status: str = "pending",
) -> CallTask:
    get_lead_or_404(session, company_id, lead_id)

    task = CallTask(
        company_id=company_id,
        lead_id=lead_id,
        campaign_id=campaign_id,
        campaign_step_id=campaign_step_id,
        campaign_recipient_id=campaign_recipient_id,
        assigned_user_id=assigned_user_id,
        status=initial_status,
        scheduled_at=scheduled_at,
        attempt_count=0,
        max_attempts=max_attempts,
        batch_id=batch_id,
        dialer_source=dialer_source,
        notes=notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def list_call_tasks(
    session: Session,
    company_id: int,
    status: Optional[str] = None,
    user_id: Optional[int] = None,
) -> list[CallTask]:
    query = select(CallTask).where(CallTask.company_id == company_id)
    if status:
        query = query.where(CallTask.status == status)
    if user_id:
        query = query.where(CallTask.assigned_user_id == user_id)

    return session.exec(
        query.order_by(CallTask.created_at.desc())
    ).all()


def queue_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
) -> CallTask:
    task = get_call_task_or_404(session, company_id, task_id)

    if task.status not in {"pending", "failed"}:
        raise HTTPException(status_code=400, detail="Task cannot be queued from current status")

    task.status = "queued"
    task.updated_at = utc_now()
    task.updated_by = actor_user_id
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def start_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
    interaction_id: Optional[int] = None,
) -> CallTask:
    task = get_call_task_or_404(session, company_id, task_id)

    if task.status not in {"pending", "queued", "retry_scheduled", "failed"}:
        raise HTTPException(status_code=400, detail="Task cannot be started from current status")

    task.status = "dialing"
    task.started_at = utc_now()
    task.attempt_count += 1
    task.retry_after = None
    if interaction_id is not None:
        task.interaction_id = interaction_id
    task.updated_at = utc_now()
    task.updated_by = actor_user_id

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def complete_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
    interaction_id: Optional[int] = None,
    outcome: Optional[str] = None,
) -> CallTask:
    task = get_call_task_or_404(session, company_id, task_id)

    task.status = "completed"
    task.completed_at = utc_now()
    task.retry_after = None
    if interaction_id is not None:
        task.interaction_id = interaction_id
    if outcome is not None:
        task.last_outcome = outcome
    task.updated_at = utc_now()
    task.updated_by = actor_user_id

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def fail_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
    interaction_id: Optional[int] = None,
    outcome: Optional[str] = None,
) -> CallTask:
    task = get_call_task_or_404(session, company_id, task_id)

    task.status = "failed"
    task.retry_after = None
    if interaction_id is not None:
        task.interaction_id = interaction_id
    if outcome is not None:
        task.last_outcome = outcome
    task.updated_at = utc_now()
    task.updated_by = actor_user_id

    session.add(task)
    session.commit()
    session.refresh(task)
    return task
