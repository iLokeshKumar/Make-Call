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

from models.models import CallTask, Campaign, CampaignRecipient, Lead, utc_now
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
    current = lead.ism_stage or "new"
    idx = _stage_index(current)
    if idx + 1 < len(ISM_STAGE_ORDER):
        next_stage = ISM_STAGE_ORDER[idx + 1]
    else:
        next_stage = current
    lead.ism_stage = next_stage
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

    stage = lead.ism_stage or "new"

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


# ---------------------------------------------------------------------------
# Batch runner — called by the automation worker
# ---------------------------------------------------------------------------

def run_ism_for_company(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 50,
) -> list[ISMResult]:
    """
    Run one ISM cycle for every active, non-terminal lead in *company_id*.

    The individual `run_ism_cycle` calls already enforce cooldown windows and
    channel guards, so this function only needs to pull eligible lead IDs and
    dispatch.  Leads where all channels are in cooldown are skipped cheaply
    via the global-cooldown guard inside `run_ism_cycle`.

    Args:
        session:        DB session (passed in by the worker so locking is shared).
        company_id:     Tenant boundary.
        actor_user_id:  The user ID recorded on any created tasks/interactions.
        limit:          Max leads to process per cycle (prevents runaway cycles).

    Returns:
        List of per-lead ISM result dicts (same shape as `run_ism_cycle`).
    """
    from datetime import timedelta

    from models.models import Lead, utc_now

    # Pull active leads that are not in terminal stages.
    # We also pre-filter on `last_outreach_at` to avoid loading thousands of
    # rows when most are in cooldown — the tightest cooldown window is 6h
    # (WhatsApp), so any lead outreached in the last 6h can be skipped here.
    min_cooldown_hours = min(_CHANNEL_COOLDOWN_HOURS.values())
    cutoff = utc_now() - timedelta(hours=min_cooldown_hours)

    leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.ism_stage.notin_(list(_TERMINAL_STAGES)),  # type: ignore[arg-type]
        ).where(
            (Lead.last_outreach_at == None) | (Lead.last_outreach_at <= cutoff)  # noqa: E711
        ).order_by(
            Lead.next_action_due_at.asc().nullsfirst(),
            Lead.id.asc(),
        ).limit(limit)
    ).all()

    if not leads:
        logger.info("ISM[company=%d]: no eligible leads found", company_id)
        return []

    # Build a set of lead IDs that are actively enrolled in a running campaign
    # so ISM doesn't double-process them.
    active_campaign_lead_ids: set[int] = set()
    active_enrolled = session.exec(
        select(CampaignRecipient.lead_id).join(
            Campaign, Campaign.id == CampaignRecipient.campaign_id
        ).where(
            CampaignRecipient.company_id == company_id,
            CampaignRecipient.status == "active",
            Campaign.status == "active",
        )
    ).all()
    active_campaign_lead_ids = {lid for lid in active_enrolled if lid is not None}

    logger.info(
        "ISM[company=%d]: processing %d eligible leads (%d skipped — active campaign)",
        company_id, len(leads), sum(1 for l in leads if l.id in active_campaign_lead_ids),
    )

    results: list[ISMResult] = []
    for lead in leads:
        if lead.id in active_campaign_lead_ids:
            results.append({
                "lead_id": lead.id,
                "skipped": True,
                "skip_reason": "managed_by_active_campaign",
            })
            continue
        try:
            result = run_ism_cycle(
                session=session,
                company_id=company_id,
                lead_id=lead.id,
                actor_user_id=actor_user_id,
            )
            results.append(result)
        except Exception:  # noqa: BLE001
            logger.exception("ISM[company=%d]: unhandled error for lead=%d", company_id, lead.id)
            results.append({
                "lead_id": lead.id,
                "skipped": True,
                "skip_reason": "unhandled_exception",
            })

    dispatched = sum(1 for r in results if not r.get("skipped"))
    skipped = len(results) - dispatched
    logger.info(
        "ISM[company=%d]: done | leads=%d dispatched=%d skipped=%d",
        company_id, len(leads), dispatched, skipped,
    )
    return results
