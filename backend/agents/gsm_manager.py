"""
GSM Manager Agent — Territory governance, exception approvals, field team coaching.

Invoked by the worker via orchestrator.run_agent(agent_name="gsm_manager", ...)
when an AgentTask has assigned_agent="gsm_manager".
This is a workflow/policy agent (no LLM calls).
"""
from __future__ import annotations

import logging
from typing import Any

from sqlmodel import Session, select

from models.models import (
    AgentApproval,
    AgentTask,
    CallCoachScore,
    Lead,
    Outcome,
    utc_now,
)

logger = logging.getLogger(__name__)

_VALID_ACTIONS = frozenset(
    ["review_territory", "approve_exception", "coach_rep", "assign_visit"]
)


def _err(msg: str) -> dict:
    return {"status": "error", "error": msg}


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _review_territory(session: Session, task: AgentTask, inp: dict) -> dict:
    territory_data: dict = inp.get("territory_data") or {}
    state_filter: str | None = territory_data.get("state")
    city_filter: str | None = territory_data.get("city")

    stmt = select(Lead).where(Lead.company_id == task.company_id)
    if state_filter:
        stmt = stmt.where(Lead.state == state_filter)
    if city_filter:
        stmt = stmt.where(Lead.city == city_filter)

    leads = session.exec(stmt).all()

    # Count by ism_stage
    stage_counts: dict[str, int] = {}
    for lead in leads:
        stage = lead.ism_stage or "new"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    # Conversion rate: closed_won / total non-new leads that progressed past new
    total = len(leads)
    closed_won = stage_counts.get("closed_won", 0)
    closed_lost = stage_counts.get("closed_lost", 0)
    converted = closed_won
    attempted = total - stage_counts.get("new", 0)
    conversion_rate = round(converted / attempted, 4) if attempted > 0 else 0.0

    return {
        "territory_data": territory_data,
        "total_leads": total,
        "stage_breakdown": stage_counts,
        "closed_won": closed_won,
        "closed_lost": closed_lost,
        "conversion_rate": conversion_rate,
    }


def _approve_exception(session: Session, task: AgentTask, inp: dict) -> dict:
    approval_id = inp.get("approval_id")
    if not approval_id:
        return _err("approval_id is required for approve_exception")

    approval = session.exec(
        select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.company_id == task.company_id,
        )
    ).first()
    if not approval:
        return _err(f"AgentApproval {approval_id} not found")

    if approval.status != "pending":
        return _err(f"Approval {approval_id} is already in status={approval.status!r}")

    approval.status = "approved"
    approval.reviewed_at = utc_now()
    # reviewer_id=None signals automated approval by the GSM Manager agent
    approval.reviewer_id = None
    approval.reviewer_note = "Auto-approved by GSM Manager agent"
    approval.updated_at = utc_now()
    approval.updated_by = task.created_by
    session.add(approval)
    session.commit()

    return {
        "approval_id": approval_id,
        "action_type": approval.action_type,
        "status": "approved",
        "reviewed_at": approval.reviewed_at.isoformat() if approval.reviewed_at else None,
    }


def _coach_rep(session: Session, task: AgentTask, inp: dict) -> dict:
    user_id = inp.get("user_id")
    if not user_id:
        return _err("user_id is required for coach_rep")

    # Find all leads assigned to this user so we can look up their call coach scores
    lead_ids_stmt = select(Lead.id).where(
        Lead.company_id == task.company_id,
        Lead.owner_user_id == user_id,
    )
    lead_ids = [row for row in session.exec(lead_ids_stmt).all()]

    if not lead_ids:
        return {
            "user_id": user_id,
            "message": "No leads assigned to this rep",
            "avg_scores": {},
            "top_weaknesses": [],
        }

    scores = session.exec(
        select(CallCoachScore).where(
            CallCoachScore.company_id == task.company_id,
            CallCoachScore.lead_id.in_(lead_ids),
        )
    ).all()

    if not scores:
        return {
            "user_id": user_id,
            "message": "No coaching scores found for this rep's leads",
            "avg_scores": {},
            "top_weaknesses": [],
        }

    # Compute averages per dimension
    dimensions = [
        "score_rapport",
        "score_discovery",
        "score_objection_handling",
        "score_value_proposition",
        "score_closing",
        "score_overall",
    ]
    totals: dict[str, list[int]] = {d: [] for d in dimensions}
    weaknesses: list[str] = []

    for score in scores:
        for dim in dimensions:
            val = getattr(score, dim, None)
            if val is not None:
                totals[dim].append(val)
        if score.weaknesses:
            weaknesses.append(score.weaknesses)

    avg_scores = {
        dim: round(sum(vals) / len(vals), 2) if vals else None
        for dim, vals in totals.items()
    }

    return {
        "user_id": user_id,
        "total_calls_reviewed": len(scores),
        "avg_scores": avg_scores,
        "top_weaknesses": weaknesses[:5],  # surface the most recent 5
    }


def _assign_visit(session: Session, task: AgentTask, inp: dict) -> dict:
    lead_id = inp.get("lead_id")
    user_id = inp.get("user_id")
    visit_date = inp.get("visit_date")

    if not lead_id:
        return _err("lead_id is required for assign_visit")
    if not user_id:
        return _err("user_id is required for assign_visit")

    # Verify lead exists and belongs to this company
    lead = session.exec(
        select(Lead).where(Lead.id == lead_id, Lead.company_id == task.company_id)
    ).first()
    if not lead:
        return _err(f"Lead {lead_id} not found")

    from services.agent.agent_task_service import create_agent_task
    gsm_task = create_agent_task(
        session=session,
        company_id=task.company_id,
        task_type="field_visit",
        assigned_agent="gsm",
        input_json={
            "action": "plan_visit",
            "lead_id": lead_id,
            "visit_date": visit_date or "",
            "assigned_user_id": user_id,
            "actor_user_id": task.created_by,
        },
        lead_id=lead_id,
        priority=3,
        actor_user_id=task.created_by,
    )

    return {
        "lead_id": lead_id,
        "assigned_user_id": user_id,
        "enqueued_gsm_task_id": gsm_task.id,
        "visit_date": visit_date,
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

    logger.info(
        "[GSMManagerAgent] action=%s user_id=%s company=%s",
        action, inp.get("user_id"), task.company_id,
    )

    try:
        if action == "review_territory":
            result = _review_territory(session, task, inp)
        elif action == "approve_exception":
            result = _approve_exception(session, task, inp)
        elif action == "coach_rep":
            result = _coach_rep(session, task, inp)
        elif action == "assign_visit":
            result = _assign_visit(session, task, inp)
        else:
            result = _err(f"Unhandled action: {action!r}")
    except Exception as exc:
        logger.exception("[GSMManagerAgent] action=%s failed: %s", action, exc)
        return _err(f"GSM Manager agent internal error: {exc}")

    return {"status": "ok", "action": action, "result": result}
