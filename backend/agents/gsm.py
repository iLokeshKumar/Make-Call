"""
GSM Agent — Ground Sales Manager.

Manages field sales visits, on-ground notes, and triggers quote/order workflows.
This is a workflow/policy agent (no LLM calls). Invoked by the worker via
orchestrator.run_agent(agent_name="gsm", ...) when an AgentTask has
assigned_agent="gsm".
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from models.models import (
    AgentApproval,
    AgentTask,
    Appointment,
    Lead,
    utc_now,
)

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset(
    ["plan_visit", "record_visit_notes", "trigger_quote_revision", "request_special_terms"]
)


def _err(msg: str) -> dict:
    return {"status": "error", "error": msg}


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _plan_visit(session: Session, task: AgentTask, inp: dict) -> dict:
    lead_id = inp.get("lead_id")
    visit_date_str = inp.get("visit_date")

    if not lead_id:
        return _err("lead_id is required for plan_visit")
    if not visit_date_str:
        return _err("visit_date is required for plan_visit")

    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == task.company_id)
    ).first()
    if not lead:
        return _err(f"Lead {lead_id} not found")

    try:
        visit_dt = datetime.fromisoformat(visit_date_str)
        if visit_dt.tzinfo is None:
            visit_dt = visit_dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return _err(f"Invalid visit_date format: {visit_date_str!r}. Use ISO 8601.")

    appt = Appointment(
        company_id=task.company_id,
        lead_id=lead_id,
        appointment_time=visit_dt,
        status="scheduled",
        notes="[GSM] Field visit scheduled",
        created_by=task.created_by,
        updated_by=task.created_by,
    )
    session.add(appt)

    lead.next_action = "field_visit"
    lead.next_action_due_at = visit_dt
    lead.updated_at = utc_now()
    lead.updated_by = task.created_by
    session.add(lead)

    session.commit()
    session.refresh(appt)

    return {
        "appointment_id": appt.id,
        "lead_id": lead_id,
        "visit_date": visit_dt.isoformat(),
        "lead_next_action": "field_visit",
    }


def _record_visit_notes(session: Session, task: AgentTask, inp: dict) -> dict:
    lead_id = inp.get("lead_id")
    notes = inp.get("notes", "")
    outcome = inp.get("outcome", "")

    if not lead_id:
        return _err("lead_id is required for record_visit_notes")

    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == task.company_id)
    ).first()
    if not lead:
        return _err(f"Lead {lead_id} not found")

    timestamp = utc_now().isoformat()
    appended_note = f"\n[{timestamp}] GSM Visit — outcome: {outcome}\n{notes}".strip()
    lead.notes = ((lead.notes or "") + "\n" + appended_note).strip()
    lead.updated_at = utc_now()
    lead.updated_by = task.created_by

    enqueued_task_id = None

    if outcome == "ready_to_order":
        lead.ism_stage = "quote_sent"
        # Enqueue a quote agent task
        from services.agent.agent_task_service import create_agent_task
        quote_task = create_agent_task(
            session=session,
            company_id=task.company_id,
            task_type="create_quote",
            assigned_agent="quote",
            input_json={
                "lead_id": lead_id,
                "trigger": "gsm_visit_outcome",
                "notes": notes,
                "actor_user_id": task.created_by,
            },
            lead_id=lead_id,
            priority=3,
            actor_user_id=task.created_by,
        )
        enqueued_task_id = quote_task.id

    elif outcome == "not_interested":
        lead.ism_stage = "closed_lost"

    session.add(lead)
    session.commit()

    return {
        "lead_id": lead_id,
        "outcome": outcome,
        "ism_stage": lead.ism_stage,
        "notes_appended": True,
        "enqueued_quote_task_id": enqueued_task_id,
    }


def _trigger_quote_revision(session: Session, task: AgentTask, inp: dict) -> dict:
    lead_id = inp.get("lead_id")
    revision_notes = inp.get("notes", "")

    if not lead_id:
        return _err("lead_id is required for trigger_quote_revision")

    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == task.company_id)
    ).first()
    if not lead:
        return _err(f"Lead {lead_id} not found")

    from services.agent.agent_task_service import create_agent_task
    quote_task = create_agent_task(
        session=session,
        company_id=task.company_id,
        task_type="revise_quote",
        assigned_agent="quote",
        input_json={
            "lead_id": lead_id,
            "revision_notes": revision_notes,
            "trigger": "gsm_quote_revision",
            "actor_user_id": task.created_by,
        },
        lead_id=lead_id,
        priority=3,
        actor_user_id=task.created_by,
    )

    return {
        "lead_id": lead_id,
        "enqueued_quote_revision_task_id": quote_task.id,
        "revision_notes": revision_notes,
    }


def _request_special_terms(session: Session, task: AgentTask, inp: dict) -> dict:
    lead_id = inp.get("lead_id")
    special_terms = inp.get("special_terms") or {}

    if not lead_id:
        return _err("lead_id is required for request_special_terms")

    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == task.company_id)
    ).first()
    if not lead:
        return _err(f"Lead {lead_id} not found")

    approval = AgentApproval(
        company_id=task.company_id,
        task_id=task.id,
        action_type="special_terms_request",
        action_summary=(
            f"Special terms requested for lead {lead_id} ({lead.name}): "
            f"{special_terms}"
        ),
        action_payload={
            "lead_id": lead_id,
            "special_terms": special_terms,
            "requested_by": task.created_by,
        },
        status="pending",
        created_by=task.created_by,
        updated_by=task.created_by,
    )
    session.add(approval)
    session.commit()
    session.refresh(approval)

    return {
        "lead_id": lead_id,
        "approval_id": approval.id,
        "action_type": "special_terms_request",
        "status": "pending",
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """
    Entry point called by the worker via orchestrator.run_agent.

    Args:
        session: Active SQLModel session.
        task:    The AgentTask record being processed. All input is read
                 from task.input_json.

    Returns:
        A JSON-serialisable dict written to AgentTask.output_json.
    """
    inp: dict[str, Any] = task.input_json or {}
    action = inp.get("action", "")

    if action not in _VALID_ACTIONS:
        return _err(
            f"Unknown action {action!r}. Valid: {sorted(_VALID_ACTIONS)}"
        )

    logger.info("[GSMAgent] action=%s lead_id=%s company=%s", action, inp.get("lead_id"), task.company_id)

    try:
        if action == "plan_visit":
            result = _plan_visit(session, task, inp)
        elif action == "record_visit_notes":
            result = _record_visit_notes(session, task, inp)
        elif action == "trigger_quote_revision":
            result = _trigger_quote_revision(session, task, inp)
        elif action == "request_special_terms":
            result = _request_special_terms(session, task, inp)
        else:
            result = _err(f"Unhandled action: {action!r}")
    except Exception as exc:
        logger.exception("[GSMAgent] action=%s failed: %s", action, exc)
        return _err(f"GSM agent internal error: {exc}")

    return {"status": "ok", "action": action, "result": result}
