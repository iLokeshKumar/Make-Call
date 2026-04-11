"""
Outcome Service: Foundation for all call automation
Handles call outcome normalization, classification, retry policies, and lead state transitions.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import CampaignRecipient, CallTask, Interaction, Lead, utc_now
from services.outbound_call_service import get_call_task_or_404

logger = logging.getLogger(__name__)

# Canonical call outcome values
OUTCOME_ANSWERED = "answered"
OUTCOME_NO_ANSWER = "no_answer"
OUTCOME_BUSY = "busy"
OUTCOME_FAILED = "failed"
OUTCOME_INTERESTED = "answered_interested"
OUTCOME_NOT_INTERESTED = "answered_not_interested"
OUTCOME_CALLBACK_REQUESTED = "answered_callback_requested"
OUTCOME_FOLLOW_UP = "answered_follow_up_needed"
OUTCOME_VOICEMAIL = "voicemail"

# Signal detection patterns
POSITIVE_SIGNALS = {
    "interested", "yes", "tell me", "send", "share", "proposal",
    "pricing", "demo", "meeting", "call", "available", "excited",
    "let's do", "sounds good", "schedule demo", "send quote"
}
NEGATIVE_SIGNALS = {
    "not interested", "no", "stop", "remove", "unsubscribe", "not now",
    "later", "busy", "wrong", "no thanks", "not good", "don't call"
}
CALLBACK_SIGNALS = {
    "call back", "callback", "call me", "speak", "ring me", "later",
    "call me back", "call me later", "later today", "later tomorrow"
}

ANSWERED_OUTCOMES = {
    OUTCOME_INTERESTED,
    OUTCOME_NOT_INTERESTED,
    OUTCOME_CALLBACK_REQUESTED,
    OUTCOME_FOLLOW_UP,
}

FINAL_OUTCOMES = ANSWERED_OUTCOMES | {OUTCOME_VOICEMAIL, OUTCOME_BUSY, OUTCOME_NO_ANSWER, OUTCOME_FAILED}


def _safe_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception:
        return None


def normalize_call_outcome(
    raw_status: str | None,
    transcript: str | None = None,
    interaction: Interaction | None = None,
) -> str:
    """
    Normalize raw call status to canonical outcome string.
    Considers status, transcript signals, and interaction metadata.
    """
    lowered_status = (raw_status or "").strip().lower()
    lowered_transcript = (transcript or "").strip().lower()

    # Direct status mappings
    if lowered_status in FINAL_OUTCOMES:
        return lowered_status

    # Analyze based on answered status + transcript
    if lowered_status in {"completed", "answered", "in_progress"} and lowered_transcript:
        if any(term in lowered_transcript for term in NEGATIVE_SIGNALS):
            return OUTCOME_NOT_INTERESTED
        if any(term in lowered_transcript for term in CALLBACK_SIGNALS):
            return OUTCOME_CALLBACK_REQUESTED
        if any(term in lowered_transcript for term in POSITIVE_SIGNALS):
            return OUTCOME_INTERESTED
        return OUTCOME_FOLLOW_UP

    # Terminal status mappings
    if lowered_status in {"busy"}:
        return OUTCOME_BUSY
    if lowered_status in {"no-answer", "no_answer", "ringing", "canceled", "cancelled"}:
        return OUTCOME_NO_ANSWER
    if lowered_status in {"voicemail", "machine", "answering_machine"}:
        return OUTCOME_VOICEMAIL
    if lowered_status in {"failed", "error"}:
        return OUTCOME_FAILED

    # Interaction-based fallback
    if interaction and interaction.status == "completed" and lowered_transcript:
        return normalize_call_outcome("completed", lowered_transcript, None)

    return OUTCOME_FAILED


def classify_outcome_from_transcript(
    llm_service: Any,
    transcript: str,
    lead_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Classify call outcome from transcript using heuristics or LLM.
    
    Returns:
    {
        "normalized_outcome": str,
        "confidence": Decimal,
        "summary": str,
        "signals": list[str],
        "suggested_next_action": str,
    }
    """
    lowered = (transcript or "").strip().lower()
    if not lowered:
        return {
            "normalized_outcome": OUTCOME_FAILED,
            "confidence": Decimal("0.25"),
            "summary": "No transcript available to classify.",
            "signals": [],
            "suggested_next_action": "none",
        }

    # Heuristic classification
    heuristic = normalize_call_outcome("completed", transcript)
    summary = transcript.strip().replace("\n", " ")[:240]
    signals: list[str] = []
    
    # Extract signals
    if heuristic == OUTCOME_INTERESTED:
        signals.append("positive_interest_detected")
    elif heuristic == OUTCOME_NOT_INTERESTED:
        signals.append("negative_intent_detected")
    elif heuristic == OUTCOME_CALLBACK_REQUESTED:
        signals.append("callback_requested")
    
    # Add specific signal terms found
    for sig in POSITIVE_SIGNALS:
        if sig in lowered:
            signals.append(f"signal_{sig.replace(' ', '_')}")
    for sig in NEGATIVE_SIGNALS:
        if sig in lowered:
            signals.append(f"signal_{sig.replace(' ', '_')}")

    # Try LLM if available
    if llm_service:
        try:
            prompt = (
                "Classify this sales call into one of: "
                "answered_interested, answered_not_interested, answered_callback_requested, "
                "answered_follow_up_needed, voicemail, busy, no_answer, failed. "
                "Return JSON with keys: normalized_outcome, confidence (0-100), summary, suggested_next_action.\n\n"
                f"TRANSCRIPT:\n{transcript[:1000]}"
            )
            result_text = llm_service.invoke(prompt)
            payload = json.loads(result_text)
            normalized = str(payload.get("normalized_outcome") or heuristic).strip().lower()
            if normalized in FINAL_OUTCOMES:
                return {
                    "normalized_outcome": normalized,
                    "confidence": _safe_decimal(payload.get("confidence")) or Decimal("0.70"),
                    "summary": str(payload.get("summary") or summary)[:500],
                    "signals": signals,
                    "suggested_next_action": payload.get("suggested_next_action") or _suggest_action_from_outcome(normalized),
                }
        except Exception as e:
            logger.debug(f"LLM classification failed, using heuristics: {e}")

    # Fallback: heuristic + suggested action
    suggested_next_action = _suggest_action_from_outcome(heuristic)

    return {
        "normalized_outcome": heuristic,
        "confidence": Decimal("0.70"),
        "summary": summary,
        "signals": signals,
        "suggested_next_action": suggested_next_action,
    }


def _suggest_action_from_outcome(outcome: str) -> str:
    """Suggest next action based on outcome."""
    action_map = {
        OUTCOME_INTERESTED: "send_quote",
        OUTCOME_NOT_INTERESTED: "close_lost",
        OUTCOME_CALLBACK_REQUESTED: "follow_up_call",
        OUTCOME_FOLLOW_UP: "follow_up_email",
        OUTCOME_NO_ANSWER: "retry",
        OUTCOME_BUSY: "retry",
        OUTCOME_VOICEMAIL: "follow_up",
        OUTCOME_FAILED: "retry",
    }
    return action_map.get(outcome, "none")


def get_retry_policy(
    outcome: str,
    attempt_count: int,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Determine retry policy based on outcome and attempt count.
    
    Returns:
    {
        "should_retry": bool,
        "retry_after_hours": int | None,
        "max_attempts": int,
        "max_attempts_reached": bool,
    }
    """
    # Retry configuration by outcome
    retry_config = {
        OUTCOME_NO_ANSWER: {"max_attempts": 6, "retry_hours": [1, 2, 4, 8, 16, 24]},
        OUTCOME_BUSY: {"max_attempts": 4, "retry_hours": [2, 4, 8, 24]},
        OUTCOME_FAILED: {"max_attempts": 2, "retry_hours": [12, 24]},
        OUTCOME_VOICEMAIL: {"max_attempts": 2, "retry_hours": [24, 72]},
        OUTCOME_CALLBACK_REQUESTED: {"max_attempts": 1, "retry_hours": []},
        OUTCOME_INTERESTED: {"max_attempts": 1, "retry_hours": []},
        OUTCOME_NOT_INTERESTED: {"max_attempts": 1, "retry_hours": []},
        OUTCOME_FOLLOW_UP: {"max_attempts": 1, "retry_hours": []},
        OUTCOME_ANSWERED: {"max_attempts": 1, "retry_hours": []},
    }
    
    config_for_outcome = retry_config.get(outcome, {"max_attempts": 1, "retry_hours": []})
    max_attempts = config_for_outcome["max_attempts"]
    retry_hours_list = config_for_outcome["retry_hours"]
    
    max_attempts_reached = attempt_count >= max_attempts
    should_retry = not max_attempts_reached and attempt_count < len(retry_hours_list)
    
    retry_after_hours = None
    if attempt_count < len(retry_hours_list):
        retry_after_hours = retry_hours_list[attempt_count]
    
    return {
        "should_retry": should_retry,
        "retry_after_hours": retry_after_hours,
        "max_attempts": max_attempts,
        "max_attempts_reached": max_attempts_reached,
    }


_ISM_STAGE_ORDER = [
    "new", "contacted", "engaged", "quote_sent", "negotiation", "closed_won", "closed_lost"
]


def _ism_stage_index(stage: str) -> int:
    try:
        return _ISM_STAGE_ORDER.index(stage)
    except ValueError:
        return 0


def advance_ism_stage(lead: Lead, target_stage: str) -> bool:
    """
    Move lead.ism_stage to target_stage only if it is strictly forward.
    Returns True if the stage was updated.
    """
    current = lead.ism_stage or "new"
    if _ism_stage_index(target_stage) > _ism_stage_index(current):
        lead.ism_stage = target_stage
        return True
    return False


# Outcome → ISM stage target
_OUTCOME_ISM_STAGE: dict[str, str] = {
    OUTCOME_INTERESTED:        "engaged",
    OUTCOME_CALLBACK_REQUESTED: "contacted",
    OUTCOME_FOLLOW_UP:          "contacted",
    OUTCOME_NOT_INTERESTED:    "closed_lost",
}


def derive_lead_status_patch(outcome: str) -> dict[str, Any]:
    """
    Map call outcome to lead field updates.

    Returns dict of Lead field updates.
    """
    mapping: dict[str, dict[str, Any]] = {
        OUTCOME_INTERESTED: {
            "status": "contacted",
            "qualification_status": "qualified",
            "next_action": "send_quote",
        },
        OUTCOME_CALLBACK_REQUESTED: {
            "status": "contacted",
            "qualification_status": "follow_up",
            "next_action": "follow_up_call",
        },
        OUTCOME_FOLLOW_UP: {
            "status": "contacted",
            "qualification_status": "follow_up",
            "next_action": "follow_up_email",
        },
        OUTCOME_NOT_INTERESTED: {
            "status": "closed_lost",
            "qualification_status": "not_interested",
            "next_action": "none",
        },
    }
    return mapping.get(outcome, {})



def _update_campaign_recipient_for_outcome(
    session: Session,
    task: CallTask,
    actor_user_id: int,
    normalized_outcome: str,
    retry_after_hours: int | None,
) -> None:
    if not task.campaign_recipient_id:
        return

    recipient = session.exec(
        select(CampaignRecipient).where(
            CampaignRecipient.id == task.campaign_recipient_id,
            CampaignRecipient.company_id == task.company_id,
        )
    ).first()
    if not recipient:
        return

    recipient.updated_at = utc_now()
    recipient.updated_by = actor_user_id
    if normalized_outcome in ANSWERED_OUTCOMES:
        recipient.last_contact_at = utc_now()
        if task.interaction_id is not None:
            recipient.last_interaction_id = task.interaction_id
        session.add(recipient)
        session.commit()
        from services.campaign_service import schedule_campaign_recipient_next_step

        schedule_campaign_recipient_next_step(
            session=session,
            company_id=task.company_id,
            actor_user_id=actor_user_id,
            recipient=recipient,
        )
        return

    # if retry_after_hours is not None:
    #     from datetime import timedelta

    #     recipient.next_run_at = utc_now() + timedelta(hours=retry_after_hours)
    # session.add(recipient)
    # session.commit()

    if retry_after_hours is not None:
        recipient.next_run_at = utc_now() + timedelta(hours=retry_after_hours)
        recipient.status = "active"  # ← ADD THIS so the worker picks it up again
    session.add(recipient)
    session.commit()


def apply_call_outcome(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
    interaction_id: int | None,
    raw_status: str | None,
    transcript: str | None,
    confidence: Decimal | None = None,
) -> dict[str, Any]:
    task = get_call_task_or_404(session, company_id, task_id)
    interaction = session.get(Interaction, interaction_id) if interaction_id is not None else None
    normalized_outcome = normalize_call_outcome(raw_status, transcript, interaction)

    # Do not downgrade a positively answered call if a later callback posts a weaker provider status.
    if task.last_outcome in ANSWERED_OUTCOMES and normalized_outcome not in ANSWERED_OUTCOMES:
        normalized_outcome = task.last_outcome

    retry_policy = get_retry_policy(normalized_outcome, task.attempt_count)
    now = utc_now()

    if interaction is not None:
        interaction.metadata_json = {
            **(interaction.metadata_json or {}),
            "normalized_outcome": normalized_outcome,
            "provider_status": raw_status,
        }
        interaction.updated_at = now
        interaction.updated_by = actor_user_id
        if interaction_id is not None:
            task.interaction_id = interaction_id
        session.add(interaction)

    task.last_outcome = normalized_outcome
    task.outcome_confidence = confidence
    task.updated_at = now
    task.updated_by = actor_user_id

    if normalized_outcome in ANSWERED_OUTCOMES:
        task.status = "completed"
        task.completed_at = now
        task.retry_after = None
    # elif retry_policy["should_retry"]:
    #     task.status = "retry_scheduled"
    #     task.retry_after = now if retry_policy["retry_after_hours"] is None else now.replace()
    #     if retry_policy["retry_after_hours"] is not None:
    #         from datetime import timedelta

    #         task.retry_after = now + timedelta(hours=retry_policy["retry_after_hours"])
    #     task.scheduled_at = task.retry_after
    #     task.completed_at = None

    elif retry_policy["should_retry"]:
        task.status = "retry_scheduled"
        retry_hours = retry_policy["retry_after_hours"]
        task.retry_after = now + timedelta(hours=retry_hours) if retry_hours else now
        task.scheduled_at = task.retry_after
        task.completed_at = None
    else:
        task.status = "failed"
        task.retry_after = None
        task.completed_at = now

    lead = session.exec(
        select(Lead).where(
            Lead.id == task.lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    patch = derive_lead_status_patch(normalized_outcome)
    for key, value in patch.items():
        setattr(lead, key, value)

    # Advance ISM stage based on call outcome (forward-only — never goes backwards)
    target_ism = _OUTCOME_ISM_STAGE.get(normalized_outcome)
    if target_ism:
        advance_ism_stage(lead, target_ism)

    lead.last_outreach_at = now
    lead.updated_at = now
    lead.updated_by = actor_user_id

    session.add(task)
    session.add(lead)
    session.commit()
    session.refresh(task)

    _update_campaign_recipient_for_outcome(
        session=session,
        task=task,
        actor_user_id=actor_user_id,
        normalized_outcome=normalized_outcome,
        retry_after_hours=retry_policy["retry_after_hours"],
    )

    # Invalidate predictive dialer cache so next prediction uses fresh data
    try:
        from services.predictive_dialer_service import invalidate_model_cache
        invalidate_model_cache(company_id)
    except Exception:
        pass

    # Auto-CSAT: send feedback request after positive call outcomes
    if normalized_outcome in {OUTCOME_INTERESTED, OUTCOME_CALLBACK_REQUESTED}:
        try:
            from services.auto_csat_service import maybe_send_auto_csat
            maybe_send_auto_csat(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=task.lead_id,
                interaction_id=interaction_id,
                trigger="call",
                normalized_outcome=normalized_outcome,
            )
        except Exception as csat_exc:
            logger.warning("[AutoCSAT] Dispatch failed after call: %s", csat_exc)

    # Auto-CSAT: send a "we missed you" feedback email for no-answer / voicemail
    elif normalized_outcome in {OUTCOME_NO_ANSWER, OUTCOME_VOICEMAIL}:
        try:
            from services.auto_csat_service import maybe_send_auto_csat
            maybe_send_auto_csat(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=task.lead_id,
                interaction_id=interaction_id,
                trigger="missed_call",
                normalized_outcome=normalized_outcome,
            )
        except Exception as csat_exc:
            logger.warning("[AutoCSAT] Dispatch failed for missed call: %s", csat_exc)

    return {
        "task_id": task.id,
        "lead_id": lead.id,
        "normalized_outcome": normalized_outcome,
        "task_status": task.status,
        "retry_after": task.retry_after,
        "retry_policy": retry_policy,
    }
