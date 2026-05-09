"""
Agent Task Service — durable task bus for the multi-agent orchestrator.

The worker loop calls run_agent_tasks() once per cycle per company.
Individual services or routes call create_agent_task() to enqueue work.

Status lifecycle:
  pending → running → done | failed (re-queued until max_attempts)
  pending → awaiting_approval → approved → running → done | failed
                              → rejected  (terminal, skipped by worker)
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlmodel import Session, select

from models.models import AgentTask, utc_now

logger = logging.getLogger(__name__)

# Approval-required action types by default. Companies can override via AGENT_APPROVAL_ACTIONS setting (comma-separated list).
_DEFAULT_APPROVAL_REQUIRED: set[str] = {
    "send_email",
    "send_quote",
    "send_whatsapp_bulk",
    # closer agent escalates to a human when it can't drive a deal to close_won on its own. The handoff task carries the negotiation summary; a human reviewer sees it in /agents/approvals.
    "handoff",
}

# Exponential backoff delays (minutes) indexed by attempt number (0-based)
_RETRY_DELAYS_MINUTES = [2, 10, 30]


def _backoff_minutes(attempt: int) -> int:
    idx = max(0, min(attempt, len(_RETRY_DELAYS_MINUTES) - 1))
    return _RETRY_DELAYS_MINUTES[idx]


def action_requires_approval(
    session: Session,
    company_id: int,
    task_type: str,
) -> bool:
    """
    Return True if this task_type requires human approval for this company.
    Reads AGENT_APPROVAL_ACTIONS company setting; falls back to defaults.
    """
    try:
        from credentials_service import get_company_setting_value
        raw = get_company_setting_value(session, company_id, "AGENT_APPROVAL_ACTIONS")
        if raw:
            overrides = {s.strip().lower() for s in raw.split(",") if s.strip()}
            return task_type.lower() in overrides
    except Exception:
        pass
    return task_type.lower() in _DEFAULT_APPROVAL_REQUIRED


def _resolve_trace_id(explicit: str | None) -> str | None:
    """Pick the best trace_id for a new AgentTask.

    Priority: caller-supplied → request_id_var → None.  The worker dispatch
    layer fills in `task:{id}` if all of those produce empty.
    """
    if explicit:
        return explicit[:64]
    try:
        from utils.logger import request_id_var
        rid = request_id_var.get("-")
        if rid and rid != "-":
            return rid[:64]
    except Exception:  # noqa: BLE001
        pass
    return None


def create_agent_task(
    session: Session,
    company_id: int,
    task_type: str,
    assigned_agent: str,
    input_json: dict[str, Any],
    *,
    lead_id: int | None = None,
    requires_approval: bool | None = None,
    priority: int = 5,
    idempotency_key: str | None = None,
    actor_user_id: int | None = None,
    trace_id: str | None = None,
) -> AgentTask:
    """
    Enqueue a new agent task. Returns existing task if idempotency_key already exists
    and the task is in a non-terminal state (pending/running/done/awaiting_approval).
    """
    if idempotency_key:
        existing = session.exec(
            select(AgentTask).where(
                AgentTask.idempotency_key == idempotency_key,
                AgentTask.company_id == company_id,
                AgentTask.status.notin_(["failed", "rejected"]),
            )
        ).first()
        if existing:
            logger.debug("[AgentTask] Deduped task %s (key=%s)", existing.id, idempotency_key)
            return existing

    if requires_approval is None:
        requires_approval = action_requires_approval(session, company_id, task_type)

    resolved_trace = _resolve_trace_id(trace_id)

    task = AgentTask(
        company_id=company_id,
        lead_id=lead_id,
        task_type=task_type,
        assigned_agent=assigned_agent,
        priority=priority,
        status="pending",
        input_json=input_json,
        requires_approval=requires_approval,
        idempotency_key=idempotency_key,
        trace_id=resolved_trace,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(task)
    # Queue a NOTIFY in the same transaction so the worker wakes immediately on commit. No-op on sqlite (tests). Fire-and-forget on any error.
    try:
        from services.notify_listener import notify as _notify_worker
        _notify_worker(session, company_id)
    except Exception:  # noqa: BLE001
        logger.debug("[AgentTask] worker notify skipped", exc_info=True)
    session.commit()
    session.refresh(task)
    logger.info(
        "[AgentTask] Created task id=%s type=%s agent=%s approval=%s",
        task.id, task_type, assigned_agent, requires_approval,
    )
    return task


def claim_task(session: Session, task: AgentTask) -> AgentTask:
    """Mark a task as running."""
    task.status = "running"
    task.started_at = utc_now()
    task.attempts += 1
    task.updated_at = utc_now()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def complete_task(session: Session, task: AgentTask, output_json: dict[str, Any]) -> AgentTask:
    """Mark a task as done with its output."""
    task.status = "done"
    task.output_json = output_json
    task.completed_at = utc_now()
    task.updated_at = utc_now()
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def fail_task(
    session: Session,
    task: AgentTask,
    error: str,
    actor_user_id: int | None = None,
) -> AgentTask:
    """
    Fail a task attempt. Re-queues with backoff if attempts < max_attempts,
    otherwise marks as permanently failed.
    """
    task.error_json = {"error": error, "attempt": task.attempts}
    task.updated_at = utc_now()
    task.updated_by = actor_user_id

    if task.attempts < task.max_attempts:
        delay = _backoff_minutes(task.attempts - 1)
        task.status = "pending"
        task.run_after = utc_now() + timedelta(minutes=delay)
        logger.warning(
            "[AgentTask] Task %s failed (attempt %d/%d), retry in %dm: %s",
            task.id, task.attempts, task.max_attempts, delay, error[:200],
        )
    else:
        task.status = "failed"
        task.completed_at = utc_now()
        logger.error(
            "[AgentTask] Task %s permanently failed after %d attempts: %s",
            task.id, task.attempts, error[:200],
        )

    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def get_next_pending_tasks(
    session: Session,
    company_id: int,
    limit: int = 10,
) -> list[AgentTask]:
    """Return pending tasks ready to run, ordered by priority then created_at."""
    now = utc_now()
    return session.exec(
        select(AgentTask).where(
            AgentTask.company_id == company_id,
            AgentTask.status == "pending",
            AgentTask.run_after <= now,
        ).order_by(AgentTask.priority.asc(), AgentTask.created_at.asc()).limit(limit)
    ).all()


def run_agent_tasks(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 10,
) -> dict[str, Any]:
    """
    Worker entry point — process up to `limit` pending tasks for this company.

    For tasks that require approval: creates an AgentApproval record and
    sets status=awaiting_approval (skipped by this runner until approved).

    For approved or non-gated tasks: invokes orchestrator.run_agent() and
    records the result.
    """
    tasks = get_next_pending_tasks(session, company_id, limit)
    results = {"processed": 0, "done": 0, "queued_for_approval": 0, "failed": 0}

    for task in tasks:
        results["processed"] += 1

        # task needs approval but hasn't been approved yet
        if task.requires_approval and task.status == "pending":
            try:
                from services.agent.agent_approval_service import create_approval
                create_approval(
                    session=session,
                    company_id=company_id,
                    task_id=task.id,
                    action_type=task.task_type,
                    action_summary=task.input_json.get("summary", f"{task.task_type} for lead {task.lead_id}"),
                    action_payload=task.input_json,
                )
                task.status = "awaiting_approval"
                task.updated_at = utc_now()
                session.add(task)
                session.commit()
                results["queued_for_approval"] += 1
            except Exception as exc:
                logger.warning("[AgentTask] Could not create approval for task %s: %s", task.id, exc)
            continue

        # Execute — set request_id_var to the task's trace_id so logs + any sub-tasks created inside the executor inherit it.  Falls back to "task:{id}" if no trace was carried.
        from utils.logger import request_id_var
        trace = task.trace_id or f"task:{task.id}"
        token = request_id_var.set(trace)

        claim_task(session, task)
        try:
            from agents.orchestrator import run_agent
            from utils.async_bridge import run_async_from_sync

            coro = run_agent(
                agent_name=task.assigned_agent,
                query=task.input_json.get("query", ""),
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=task.lead_id,
                **{k: v for k, v in task.input_json.items() if k not in ("query", "summary")},
            )
            output = run_async_from_sync(coro)
            complete_task(session, task, output)
            results["done"] += 1
            logger.info("[AgentTask] Task %s (%s) done", task.id, task.task_type)
        except Exception as exc:
            fail_task(session, task, str(exc), actor_user_id=actor_user_id)
            results["failed"] += 1
        finally:
            try:
                request_id_var.reset(token)
            except Exception:  # noqa: BLE001
                pass

    return results
