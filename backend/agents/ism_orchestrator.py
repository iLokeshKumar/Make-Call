"""
ISM Orchestrator  –  Intelligent Sales-Motion strategy engine.

Responsibilities
----------------
1. Drive a lead through the ISM stage machine:
       new → contacted → engaged → quote_sent → negotiation → closed_won / closed_lost
2. For every stage transition, decide WHICH channel to use next (call, WhatsApp, email)
   respecting opt-outs, cooldown windows, and per-stage channel preferences.
3. Dispatch the chosen action through the appropriate service.
4. Record the outcome back on the Lead row so the automation worker can pick it up
   in the next cycle.

Design principles
-----------------
* Pure function surface: `run_ism_cycle(session, company_id, lead_id, actor_user_id)`
  is the single public entry-point used by the automation worker.
* No external I/O except the DB session passed in — easy to unit-test.
* All channel guards (opt-out, cooldown, missing contact field) are checked before
  dispatching so callers never get a partial-send situation.
"""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Literal

from sqlmodel import Session, select

from models.models import CallTask, Lead, utc_now
from services.communication_service import get_company_setting_value, send_email_to_lead
from services.message_render_service import render_template_by_id
from services.next_action_service import dispatch_next_action, handle_inbound_quote_request
from services.outbound_call_service import create_call_task
from services.tracking_service import is_lead_opted_out

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Stage ordering / progression map
# ---------------------------------------------------------------------------

ISM_STAGE_ORDER: list[str] = [
    "new",
    "contacted",
    "engaged",
    "quote_sent",
    "negotiation",
    "closed_won",
    "closed_lost",
]

# Terminal stages — we never try to progress beyond these.
_TERMINAL_STAGES: frozenset[str] = frozenset({"closed_won", "closed_lost", "do_not_call"})

# How many hours to wait between outreach attempts per channel.
_CHANNEL_COOLDOWN_HOURS: dict[str, int] = {
    "call": 24,
    "whatsapp": 6,
    "email": 12,
}

# Maximum number of attempts per channel before we stop trying it for this lead.
_CHANNEL_MAX_ATTEMPTS: dict[str, int] = {
    "call": 3,
    "whatsapp": 5,
    "email": 7,
}

# Per-stage preferred channel order (first available wins).
_STAGE_CHANNEL_PREFERENCE: dict[str, list[str]] = {
    "new":         ["call", "whatsapp", "email"],
    "contacted":   ["whatsapp", "call", "email"],
    "engaged":     ["email", "whatsapp", "call"],
    "quote_sent":  ["email", "whatsapp", "call"],
    "negotiation": ["call", "email", "whatsapp"],
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _stage_index(stage: str) -> int:
    try:
        return ISM_STAGE_ORDER.index(stage)
    except ValueError:
        return 0


def _channel_attempt_count(session: Session, company_id: int, lead_id: int, channel: str) -> int:
    """Count non-terminal outreach interactions on this channel for the lead."""
    from models.models import Interaction
    rows = session.exec(
        select(Interaction).where(
            Interaction.company_id == company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == channel,
            Interaction.direction == "outbound",
        )
    ).all()
    return len(rows)


def _channel_last_attempt_at(session: Session, company_id: int, lead_id: int, channel: str):
    """Return the most recent outbound interaction timestamp for (lead, channel) or None."""
    from models.models import Interaction
    row = session.exec(
        select(Interaction).where(
            Interaction.company_id == company_id,
            Interaction.lead_id == lead_id,
            Interaction.channel == channel,
            Interaction.direction == "outbound",
        ).order_by(Interaction.created_at.desc())
    ).first()
    return row.created_at if row else None


def _is_channel_in_cooldown(session: Session, company_id: int, lead_id: int, channel: str) -> bool:
    last = _channel_last_attempt_at(session, company_id, lead_id, channel)
    if last is None:
        return False
    cooldown_hours = _CHANNEL_COOLDOWN_HOURS.get(channel, 24)
    return utc_now() < last + timedelta(hours=cooldown_hours)


def _is_channel_exhausted(session: Session, company_id: int, lead_id: int, channel: str) -> bool:
    attempts = _channel_attempt_count(session, company_id, lead_id, channel)
    return attempts >= _CHANNEL_MAX_ATTEMPTS.get(channel, 3)


def _lead_has_channel(lead: Lead, channel: str) -> bool:
    """Check whether the lead has the contact field required by the channel."""
    if channel == "call":
        return bool(lead.normalized_phone)
    if channel == "whatsapp":
        return bool(lead.normalized_phone)
    if channel == "email":
        return bool(lead.email)
    return False


def _pick_channel(
    session: Session,
    company_id: int,
    lead: Lead,
    stage: str,
) -> str | None:
    """
    Return the best available channel for this (lead, stage) combination,
    or None if every option is blocked.
    """
    preference = _STAGE_CHANNEL_PREFERENCE.get(stage, ["call", "whatsapp", "email"])
    for channel in preference:
        if not _lead_has_channel(lead, channel):
            continue
        if is_lead_opted_out(session, company_id, lead.id, channel):
            continue
        if _is_channel_exhausted(session, company_id, lead.id, channel):
            continue
        if _is_channel_in_cooldown(session, company_id, lead.id, channel):
            continue
        return channel
    return None


# ---------------------------------------------------------------------------
# Per-channel dispatch helpers
# ---------------------------------------------------------------------------

def _dispatch_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    stage: str,
) -> dict:
    task = create_call_task(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead.id,
        assigned_user_id=lead.owner_user_id,
        scheduled_at=utc_now(),
        notes=f"ISM auto-dial – stage: {stage}",
        dialer_source="ism_orchestrator",
        initial_status="queued",
    )
    return {"channel": "call", "action": "queued_call_task", "call_task_id": task.id}


def _dispatch_whatsapp(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    stage: str,
) -> dict:
    from services.communication_service import send_whatsapp_to_lead

    template_setting = f"ISM_WHATSAPP_TEMPLATE_{stage.upper()}"
    template_id_str = get_company_setting_value(session, company_id, template_setting)
    message = None

    if template_id_str:
        try:
            rendered = render_template_by_id(
                session=session,
                company_id=company_id,
                template_id=int(template_id_str),
                lead_id=lead.id,
            )
            message = rendered.get("body")
        except Exception as exc:
            logger.warning("ISM WhatsApp template render failed (stage=%s): %s", stage, exc)

    if not message:
        message = _default_message(lead, stage, "whatsapp")

    result = send_whatsapp_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead.id,
        body=message,
    )
    return {"channel": "whatsapp", "action": "sent_whatsapp", "result": result}


def _dispatch_email(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    stage: str,
) -> dict:
    template_setting = f"ISM_EMAIL_TEMPLATE_{stage.upper()}"
    template_id_str = get_company_setting_value(session, company_id, template_setting)
    subject: str | None = None
    body: str | None = None

    if template_id_str:
        try:
            rendered = render_template_by_id(
                session=session,
                company_id=company_id,
                template_id=int(template_id_str),
                lead_id=lead.id,
            )
            subject = rendered.get("subject")
            body = rendered.get("body")
        except Exception as exc:
            logger.warning("ISM email template render failed (stage=%s): %s", stage, exc)

    if not body:
        subject = subject or _default_subject(lead, stage)
        body = _default_message(lead, stage, "email")

    result = send_email_to_lead(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead.id,
        subject=subject or _default_subject(lead, stage),
        body=body,
    )
    return {"channel": "email", "action": "sent_email", "result": result}


# ---------------------------------------------------------------------------
# Default copy (used when no template is configured)
# ---------------------------------------------------------------------------

def _default_subject(lead: Lead, stage: str) -> str:
    name = (lead.name or "there").split()[0]
    subjects: dict[str, str] = {
        "new": f"Hi {name}, quick note from us",
        "contacted": f"Following up, {name}",
        "engaged": f"Your enquiry – next steps",
        "quote_sent": f"Did you get a chance to review the quote?",
        "negotiation": f"Let's close this, {name}",
    }
    return subjects.get(stage, f"Touch-base from us, {name}")


def _default_message(lead: Lead, stage: str, channel: str) -> str:
    name = (lead.name or "there").split()[0]
    msgs: dict[str, str] = {
        "new":         f"Hi {name}, we wanted to reach out and introduce ourselves. Let us know if you have any questions!",
        "contacted":   f"Hi {name}, just following up on our earlier message. Would love to connect!",
        "engaged":     f"Hi {name}, thanks for your interest. Here is what we'd love to share next with you.",
        "quote_sent":  f"Hi {name}, just checking in on the quotation we sent. Happy to answer any questions.",
        "negotiation": f"Hi {name}, we're keen to finalise things. Let me know the best time to connect.",
    }
    return msgs.get(stage, f"Hi {name}, reaching out to stay in touch.")


# ---------------------------------------------------------------------------
# Stage transition logic
# ---------------------------------------------------------------------------

def _advance_stage(lead: Lead, actor_user_id: int, session: Session) -> str:
    """Move lead to next ISM stage and persist."""
    current = lead.status or "new"
    idx = _stage_index(current)
    if idx + 1 < len(ISM_STAGE_ORDER):
        next_stage = ISM_STAGE_ORDER[idx + 1]
    else:
        next_stage = current
    lead.status = next_stage
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()
    return next_stage


def _update_lead_after_dispatch(
    session: Session,
    lead: Lead,
    actor_user_id: int,
    channel: str,
    stage: str,
) -> None:
    """Stamp outreach metadata back onto the lead row."""
    lead.last_outreach_at = utc_now()
    lead.last_outreach_channel = channel
    lead.next_action = _next_action_for_stage(stage)
    due_hours = _CHANNEL_COOLDOWN_HOURS.get(channel, 24)
    lead.next_action_due_at = utc_now() + timedelta(hours=due_hours)
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()


def _next_action_for_stage(stage: str) -> str:
    mapping: dict[str, str] = {
        "new": "contacted",
        "contacted": "await_response",
        "engaged": "send_quote",
        "quote_sent": "follow_up",
        "negotiation": "close",
    }
    return mapping.get(stage, "follow_up")


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------

ISMResult = dict  # typed alias for readability


def run_ism_cycle(
    session: Session,
    company_id: int,
    lead_id: int,
    actor_user_id: int,
) -> ISMResult:
    """
    Execute one ISM cycle for a lead.

    Returns a dict describing what happened::

        {
            "lead_id": 42,
            "stage": "contacted",
            "channel": "call",
            "action": "queued_call_task",
            "call_task_id": 17,          # if channel == "call"
            "skipped": False,
            "skip_reason": None,
        }
    """
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()

    if not lead:
        return {"lead_id": lead_id, "skipped": True, "skip_reason": "lead_not_found"}

    stage = lead.status or "new"

    # Skip terminal / DNC leads.
    if stage in _TERMINAL_STAGES:
        return {"lead_id": lead_id, "stage": stage, "skipped": True, "skip_reason": "terminal_stage"}

    # Global cooldown: don't outreach if we already did within the tightest window.
    if lead.last_outreach_at:
        min_cooldown = min(_CHANNEL_COOLDOWN_HOURS.values())
        if utc_now() < lead.last_outreach_at + timedelta(hours=min_cooldown):
            return {"lead_id": lead_id, "stage": stage, "skipped": True, "skip_reason": "global_cooldown"}

    # Pick best available channel.
    channel = _pick_channel(session, company_id, lead, stage)
    if channel is None:
        # All channels blocked → advance stage so we don't spin forever, then give up.
        new_stage = _advance_stage(lead, actor_user_id, session)
        logger.info(
            "ISM: lead=%d all channels exhausted at stage=%s → advanced to %s",
            lead_id, stage, new_stage,
        )
        return {
            "lead_id": lead_id,
            "stage": stage,
            "skipped": True,
            "skip_reason": "all_channels_blocked",
            "advanced_to_stage": new_stage,
        }

    # Dispatch.
    try:
        if channel == "call":
            result = _dispatch_call(session, company_id, actor_user_id, lead, stage)
        elif channel == "whatsapp":
            result = _dispatch_whatsapp(session, company_id, actor_user_id, lead, stage)
        else:
            result = _dispatch_email(session, company_id, actor_user_id, lead, stage)
    except Exception as exc:
        logger.error("ISM dispatch failed: lead=%d stage=%s channel=%s error=%s", lead_id, stage, channel, exc)
        return {
            "lead_id": lead_id,
            "stage": stage,
            "channel": channel,
            "skipped": True,
            "skip_reason": f"dispatch_error: {exc}",
        }

    # Advance stage after first-touch on a new stage.
    if stage == "new":
        _advance_stage(lead, actor_user_id, session)

    # Stamp outreach back onto lead.
    _update_lead_after_dispatch(session, lead, actor_user_id, channel, stage)

    logger.info("ISM: lead=%d stage=%s channel=%s dispatched", lead_id, stage, channel)

    return {
        "lead_id": lead_id,
        "stage": stage,
        "channel": channel,
        "skipped": False,
        "skip_reason": None,
        **result,
    }
