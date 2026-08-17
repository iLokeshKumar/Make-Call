"""
ISM Manager Agent — Approves exceptions, audits transcripts, tunes scripts,
monitors funnels, reassigns leads.

Actions:
  approve_exception — Approve an AgentApproval and unblock the linked AgentTask
  audit_transcript  — Heuristic scoring of an Interaction transcript
  tune_script       — Analyse CallCoachScore records and suggest prompt improvements
  funnel_report     — Lead stage counts + conversion rate for the company
  reassign_lead     — Update Lead.owner_user_id and log an Interaction
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from models.models import (
    AgentApproval,
    AgentTask,
    CallCoachScore,
    Interaction,
    Lead,
    Outcome,
    VoiceAgentPromptVersion,
    utc_now,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_approve_exception(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    approval_id = inp.get("approval_id")
    if not approval_id:
        return {"error": "approval_id is required for approve_exception"}

    approval = session.exec(
        select(AgentApproval).where(
            AgentApproval.id == approval_id,
            AgentApproval.company_id == task.company_id,
        )
    ).first()
    if not approval:
        return {"error": f"AgentApproval {approval_id} not found"}

    now = utc_now()
    approval.status = "approved"
    approval.reviewed_at = now
    session.add(approval)

    # Also update the linked AgentTask status
    linked_task = session.exec(
        select(AgentTask).where(AgentTask.id == approval.task_id)
    ).first()
    if linked_task:
        linked_task.status = "approved"
        session.add(linked_task)

    session.commit()
    logger.info(
        "[ISMManagerAgent] Approved exception approval_id=%s (task_id=%s)",
        approval_id, approval.task_id,
    )
    return {
        "action": "approve_exception",
        "approval_id": approval_id,
        "task_id": approval.task_id,
        "status": "approved",
        "reviewed_at": now.isoformat(),
    }


def _handle_audit_transcript(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    interaction_id = inp.get("interaction_id")
    if not interaction_id:
        return {"error": "interaction_id is required for audit_transcript"}

    interaction = session.exec(
        select(Interaction).where(
            Interaction.id == interaction_id,
            Interaction.company_id == task.company_id,
        )
    ).first()
    if not interaction:
        return {"error": f"Interaction {interaction_id} not found"}

    transcript = interaction.transcript or ""
    transcript_lower = transcript.lower()

    # Heuristic scoring
    price_mentions = transcript_lower.count("price")
    has_next_step = "next step" in transcript_lower
    duration_seconds = interaction.recording_duration or 0

    objection_score = min(price_mentions, 5)   # 0–5 price mentions → objection signal
    closing_score = 10 if has_next_step else 3
    duration_flag = "short" if duration_seconds < 60 else "normal" if duration_seconds < 600 else "long"

    flags = []
    if price_mentions >= 3:
        flags.append("high_price_objection_count")
    if not has_next_step:
        flags.append("no_closing_signal")
    if duration_seconds < 60:
        flags.append("very_short_call")

    audit_result = {
        "interaction_id": interaction_id,
        "price_mention_count": price_mentions,
        "objection_signal_score": objection_score,
        "closing_signal_score": closing_score,
        "duration_seconds": duration_seconds,
        "duration_flag": duration_flag,
        "has_next_step": has_next_step,
        "flags": flags,
    }
    logger.info(
        "[ISMManagerAgent] Transcript audit for interaction %s: flags=%s",
        interaction_id, flags,
    )
    return {"action": "audit_transcript", "audit_result": audit_result}


def _handle_tune_script(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    agent_id = inp.get("agent_id")
    if not agent_id:
        return {"error": "agent_id is required for tune_script"}

    scores = session.exec(
        select(CallCoachScore)
        .where(CallCoachScore.company_id == task.company_id)
        .order_by(CallCoachScore.id.desc())  # type: ignore[arg-type]
        .limit(10)
    ).all()

    if not scores:
        return {
            "action": "tune_script",
            "agent_id": agent_id,
            "message": "No CallCoachScore records found for this company",
        }

    # Compute dimension averages
    dims = {
        "rapport": [s.score_rapport for s in scores if s.score_rapport is not None],
        "discovery": [s.score_discovery for s in scores if s.score_discovery is not None],
        "objection_handling": [s.score_objection_handling for s in scores if s.score_objection_handling is not None],
        "value_proposition": [s.score_value_proposition for s in scores if s.score_value_proposition is not None],
        "closing": [s.score_closing for s in scores if s.score_closing is not None],
    }
    averages = {k: (sum(v) / len(v)) if v else None for k, v in dims.items()}

    weak_dims = [k for k, v in averages.items() if v is not None and v < 5]

    # Fetch prompt suggestion from the weakest score record
    prompt_suggestion = None
    if weak_dims:
        for score in scores:
            if score.prompt_suggestion:
                prompt_suggestion = score.prompt_suggestion
                break

    # Fetch active prompt version for context
    active_prompt = session.exec(
        select(VoiceAgentPromptVersion).where(
            VoiceAgentPromptVersion.agent_id == agent_id,
            VoiceAgentPromptVersion.is_active == True,  # noqa: E712
        )
    ).first()

    logger.info(
        "[ISMManagerAgent] tune_script agent_id=%s weak_dims=%s", agent_id, weak_dims
    )
    return {
        "action": "tune_script",
        "agent_id": agent_id,
        "dimension_averages": averages,
        "weak_dimensions": weak_dims,
        "recommendation": (
            f"Update system prompt to improve: {', '.join(weak_dims)}" if weak_dims else "No improvements needed"
        ),
        "prompt_suggestion": prompt_suggestion,
        "active_prompt_version_id": active_prompt.id if active_prompt else None,
    }


def _handle_funnel_report(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    date_from_str = inp.get("date_from")
    date_to_str = inp.get("date_to")

    query = select(Lead).where(Lead.company_id == task.company_id)
    if date_from_str:
        try:
            from datetime import datetime
            date_from = datetime.fromisoformat(date_from_str)
            query = query.where(Lead.created_at >= date_from)
        except ValueError:
            pass
    if date_to_str:
        try:
            from datetime import datetime
            date_to = datetime.fromisoformat(date_to_str)
            query = query.where(Lead.created_at <= date_to)
        except ValueError:
            pass

    leads = session.exec(query).all()
    stage_counts: dict[str, int] = {}
    for lead in leads:
        stage = lead.ism_stage or "new"
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    # Conversion rate: closed_won / total leads
    total = len(leads)
    won = stage_counts.get("closed_won", 0)
    conversion_rate = round((won / total * 100), 2) if total > 0 else 0.0

    # Also count outcomes for reference
    outcomes = session.exec(
        select(Outcome).where(Outcome.company_id == task.company_id)
    ).all()

    logger.info(
        "[ISMManagerAgent] Funnel report: total=%d won=%d conversion_rate=%.2f%%",
        total, won, conversion_rate,
    )
    return {
        "action": "funnel_report",
        "stage_counts": stage_counts,
        "total_leads": total,
        "conversion_rate_pct": conversion_rate,
        "total_outcomes": len(outcomes),
    }


def _handle_reassign_lead(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    lead_id = inp.get("lead_id")
    new_owner_user_id = inp.get("new_owner_user_id")

    if not lead_id:
        return {"error": "lead_id is required for reassign_lead"}
    if not new_owner_user_id:
        return {"error": "new_owner_user_id is required for reassign_lead"}

    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == task.company_id,
        )
    ).first()
    if not lead:
        return {"error": f"Lead {lead_id} not found"}

    old_owner = lead.owner_user_id
    lead.owner_user_id = new_owner_user_id
    lead.updated_at = utc_now()
    session.add(lead)

    interaction = Interaction(
        company_id=task.company_id,
        lead_id=lead_id,
        type="reassignment",
        channel="internal",
        direction="internal",
        source="ism_manager_agent",
        content=f"Lead reassigned to user {new_owner_user_id}",
        started_at=utc_now(),
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    logger.info(
        "[ISMManagerAgent] Lead %d reassigned from user %s to user %s (interaction %s)",
        lead_id, old_owner, new_owner_user_id, interaction.id,
    )
    return {
        "action": "reassign_lead",
        "lead_id": lead_id,
        "previous_owner_user_id": old_owner,
        "new_owner_user_id": new_owner_user_id,
        "interaction_id": interaction.id,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate ISM manager agent action."""
    action = task.input_json.get("action")
    try:
        if action == "approve_exception":
            return _handle_approve_exception(session, task)
        elif action == "audit_transcript":
            return _handle_audit_transcript(session, task)
        elif action == "tune_script":
            return _handle_tune_script(session, task)
        elif action == "funnel_report":
            return _handle_funnel_report(session, task)
        elif action == "reassign_lead":
            return _handle_reassign_lead(session, task)
        else:
            return {
                "error": f"Unknown action: {action!r}",
                "valid_actions": [
                    "approve_exception", "audit_transcript", "tune_script",
                    "funnel_report", "reassign_lead",
                ],
            }
    except Exception as exc:
        logger.exception("[ISMManagerAgent] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}
