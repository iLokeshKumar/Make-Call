import logging
from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import CallTask, Lead, TelephonyProviderHealth, utc_now

logger = logging.getLogger(__name__)

# Priority order for provider failover
_PROVIDER_PRIORITY = ["twilio", "exotel", "enablex", "plivo", "vobiz"]


def select_healthy_provider(
    session: Session,
    company_id: int,
    preferred_provider: Optional[str] = None,
) -> str:
    """Select a healthy telephony provider for outbound calls.

    1. Reads TelephonyProviderHealth rows for the company.
    2. Filters to healthy providers (is_healthy=True, consecutive_failures < 5).
    3. If preferred_provider is healthy, returns it.
    4. Otherwise returns the first healthy provider in priority order.
    5. Falls back to "twilio" with a warning if no healthy provider found.
    """
    rows = session.exec(
        select(TelephonyProviderHealth).where(
            TelephonyProviderHealth.company_id == company_id,
        )
    ).all()

    health_map: dict[str, TelephonyProviderHealth] = {r.provider: r for r in rows}

    def _is_healthy(provider: str) -> bool:
        row = health_map.get(provider)
        if row is None:
            # No record yet means the provider hasn't been tried — treat as healthy
            return True
        return row.is_healthy and row.consecutive_failures < 5

    # Return preferred if it is healthy
    if preferred_provider and _is_healthy(preferred_provider):
        return preferred_provider

    # Walk priority order and return the first healthy one
    for provider in _PROVIDER_PRIORITY:
        if _is_healthy(provider):
            return provider

    # No healthy providers found — fallback to twilio with warning
    logger.warning(
        "[select_healthy_provider] No healthy telephony provider for company=%s; "
        "falling back to twilio",
        company_id,
    )
    return "twilio"


def record_provider_outcome(
    session: Session,
    company_id: int,
    provider: str,
    success: bool,
    error: Optional[str] = None,
) -> TelephonyProviderHealth:
    """Upsert TelephonyProviderHealth after a call attempt.

    On success: resets consecutive_failures to 0, increments success_count, marks healthy.
    On failure: increments consecutive_failures and failure_count, marks unhealthy if >= 5.
    """
    row = session.exec(
        select(TelephonyProviderHealth).where(
            TelephonyProviderHealth.company_id == company_id,
            TelephonyProviderHealth.provider == provider,
        )
    ).first()

    now = utc_now()

    if row is None:
        row = TelephonyProviderHealth(
            company_id=company_id,
            provider=provider,
            is_healthy=True,
            success_count=0,
            failure_count=0,
            consecutive_failures=0,
        )

    if success:
        row.consecutive_failures = 0
        row.success_count += 1
        row.last_success_at = now
        row.is_healthy = True
        row.last_error = None
    else:
        row.consecutive_failures += 1
        row.failure_count += 1
        row.last_failure_at = now
        if error:
            row.last_error = error[:500]
        if row.consecutive_failures >= 5:
            row.is_healthy = False
            logger.warning(
                "[record_provider_outcome] Provider %s marked unhealthy for company=%s "
                "after %d consecutive failures",
                provider, company_id, row.consecutive_failures,
            )

    row.updated_at = now
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


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
    agent_id: Optional[int] = None,
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
        agent_id=agent_id,
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


def wrapup_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
    interaction_id: Optional[int] = None,
    outcome: Optional[str] = None,
) -> CallTask:
    """Transition a call task to 'wrapup' state.

    This intermediate state is entered when a call ends (connected/conversation →
    wrapup) before post-call processing (transcript saving, outcome classification)
    completes.  Callers should invoke complete_call_task() or fail_call_task()
    once post-call work is finished.
    """
    task = get_call_task_or_404(session, company_id, task_id)

    task.status = "wrapup"
    if interaction_id is not None:
        task.interaction_id = interaction_id
    if outcome is not None:
        task.last_outcome = outcome
    task.updated_at = utc_now()
    task.updated_by = actor_user_id

    session.add(task)
    session.commit()
    session.refresh(task)
    logger.info(
        "[wrapup_call_task] task=%s transitioned to wrapup (company=%s)",
        task_id, company_id,
    )
    return task


def complete_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
    interaction_id: Optional[int] = None,
    outcome: Optional[str] = None,
    skip_wrapup: bool = False,
) -> CallTask:
    """Transition a call task to 'complete'.

    If the task is currently in connected/conversation/dialing/ringing state and
    skip_wrapup is False, the task is first transitioned through 'wrapup' to allow
    post-call processing hooks to observe the intermediate state.

    Pass skip_wrapup=True when calling from a context that has already handled the
    wrapup state (e.g. coming from wrapup_call_task directly).
    """
    task = get_call_task_or_404(session, company_id, task_id)

    # Transition through wrapup for calls ending from an active state
    _ACTIVE_STATES = {"connected", "conversation", "dialing", "ringing"}
    if not skip_wrapup and task.status in _ACTIVE_STATES:
        task.status = "wrapup"
        if interaction_id is not None:
            task.interaction_id = interaction_id
        if outcome is not None:
            task.last_outcome = outcome
        task.updated_at = utc_now()
        task.updated_by = actor_user_id
        session.add(task)
        session.commit()
        session.refresh(task)
        logger.info(
            "[complete_call_task] task=%s passed through wrapup state (company=%s)",
            task_id, company_id,
        )

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
