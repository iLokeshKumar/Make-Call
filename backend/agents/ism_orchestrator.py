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
import re
from datetime import timedelta, timezone
from typing import Literal, Optional

from sqlmodel import Session, select

from models.models import (
    Appointment,
    CallTask,
    Campaign,
    CampaignRecipient,
    Feedback,
    Lead,
    LeadRequirement,
    Quote,
    utc_now,
)
from services.communication.communication_service import get_company_setting_value
from services.message_render_service import render_template_by_id
from services.next_action_service import dispatch_next_action, handle_inbound_quote_request
from services.call.outbound_call_service import create_call_task
from services.leads.opt_out_service import is_lead_opted_out

logger = logging.getLogger(__name__)

# Stage ordering / progression map

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


# Internal helpers

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
    # Postgres stores tz-aware datetimes; SQLite tests may return naive ones.
    # Normalize to UTC-aware so the comparison works in both environments.
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
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


# Requirement-driven channel selection (2.1)
#
# When a LeadRequirement row is present, its budget + timeline can override the
# stage-based default:
#   * high-ticket  → prefer `call` (personal touch on expensive deals)
#   * urgent       → prefer `whatsapp` (fastest medium)
#   * both         → prefer `call` first, `whatsapp` second
#   * otherwise    → fall through to _STAGE_CHANNEL_PREFERENCE (unchanged)
#
# The parsers below are DELIBERATELY CONSERVATIVE — unparseable input returns
# False (no override). False negatives are safer than false positives here:
# the cost of "picked the wrong channel" is an email when a call was better,
# not a compliance violation.

_HIGH_TICKET_USD_THRESHOLD: float = 10_000.0

# Heuristic INR→USD conversion. Not intended to be precise; crossing the
# threshold by 10% either way is fine since the threshold itself is arbitrary.
_INR_TO_USD_ROUGH: float = 80.0

_BUDGET_SUFFIX_MULTIPLIERS: dict[str, float] = {
    "k": 1_000,  "thousand": 1_000,
    "m": 1_000_000, "mil": 1_000_000, "million": 1_000_000,
    "l": 100_000, "lac": 100_000, "lakh": 100_000,        # INR
    "cr": 10_000_000, "crore": 10_000_000,                # INR
}

_INR_MARKERS: tuple[str, ...] = (
    "₹", "inr", "rs ", "rs.", "rupee", "lakh", "lac", "crore",
)

# Timeline keywords that suggest "act this week or sooner"
_URGENT_TIMELINE_KEYWORDS: frozenset[str] = frozenset({
    "immediate", "urgent", "asap", "rush", "rushing",
    "today", "tomorrow", "tonight", "right now",
    "this week", "next 7 days", "next week",
})


def _budget_is_high_ticket(requirement: LeadRequirement) -> bool:
    """Return True if the requirement's budget looks ≥ ~$10k (or INR equivalent).

    Priority: explicit `structured_data["budget_max_usd"]` (number) wins.
    Fallback: heuristic regex scan of the free-text `budget_range` field.
    """
    sd = getattr(requirement, "structured_data", None) or {}
    try:
        explicit = sd.get("budget_max_usd")
        if explicit is not None:
            return float(explicit) >= _HIGH_TICKET_USD_THRESHOLD
    except (TypeError, ValueError):
        pass

    text = (getattr(requirement, "budget_range", "") or "").lower().strip()
    if not text:
        return False

    # Grab all "<number>[<suffix>]" pairs and take the max.
    max_native = 0.0
    for match in re.finditer(r"(\d+(?:[.,]\d+)?)\s*([a-z]*)", text):
        num_str, suffix = match.group(1), match.group(2)
        try:
            num = float(num_str.replace(",", ""))
        except ValueError:
            continue
        mult = _BUDGET_SUFFIX_MULTIPLIERS.get(suffix, 1.0)
        max_native = max(max_native, num * mult)

    if max_native == 0:
        return False

    # Treat as INR if any INR-indicator is in the text.
    is_inr = any(marker in text for marker in _INR_MARKERS)
    if is_inr:
        max_native = max_native / _INR_TO_USD_ROUGH

    return max_native >= _HIGH_TICKET_USD_THRESHOLD


def _timeline_is_urgent(requirement: LeadRequirement) -> bool:
    """Return True if timeline text suggests action within ~1 week.

    Explicit `structured_data["urgency"]` in {"urgent", "immediate", "rush"}
    wins. Fallback: keyword scan of `timeline` text.
    """
    sd = getattr(requirement, "structured_data", None) or {}
    urgency = sd.get("urgency")
    if isinstance(urgency, str) and urgency.lower() in {"urgent", "immediate", "rush"}:
        return True

    text = (getattr(requirement, "timeline", "") or "").lower().strip()
    if not text:
        return False

    return any(kw in text for kw in _URGENT_TIMELINE_KEYWORDS)


def _requirement_preferred_channels(
    session: Session,
    company_id: int,
    lead_id: int,
) -> list[str] | None:
    """Read the latest LeadRequirement and return channel preference, or None.

    None means "no override — use the stage default."
    """
    req = session.exec(
        select(LeadRequirement)
        .where(
            LeadRequirement.company_id == company_id,
            LeadRequirement.lead_id == lead_id,
        )
        # Tiebreak by id in case two rows share a created_at (fast test inserts,
        # batch extraction writes). Without this, order is SQL-dialect-dependent.
        .order_by(LeadRequirement.created_at.desc(), LeadRequirement.id.desc())
    ).first()
    if not req:
        return None

    is_high_ticket = _budget_is_high_ticket(req)
    is_urgent = _timeline_is_urgent(req)

    if is_high_ticket:
        # Personal touch first. Email last because high-ticket deals rarely
        # close over email.
        return ["call", "whatsapp", "email"]
    if is_urgent:
        # Fastest-response channel first. Call second because phone tag wastes
        # the urgency signal.
        return ["whatsapp", "call", "email"]
    return None


def _pick_channel(
    session: Session,
    company_id: int,
    lead: Lead,
    stage: str,
) -> str | None:
    """
    Return the best available channel for this (lead, stage) combination,
    or None if every option is blocked.

    Requirement-driven overrides (budget, timeline) take priority over the
    stage default. Guards (opt-out, cooldown, exhaustion, missing contact)
    still apply — a requirement can't force us to break an opt-out.
    """
    preference = _requirement_preferred_channels(session, company_id, lead.id)
    if preference is None:
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


# Per-channel dispatch helpers

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


def _ism_trigger(stage: str, attempt_count: int) -> str:
    """Build a stable-per-attempt trigger string for idempotency keys.

    Including `attempt_count` means: same stage + same template rendering +
    same attempt number all dedupe (worker retries harmlessly). Each NEW
    attempt gets a different key so re-dispatch after cooldown creates
    a fresh task.
    """
    return f"ism_stage:{stage}:attempt:{attempt_count}"


def _dispatch_whatsapp(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    stage: str,
) -> dict:
    """Enqueue a WhatsApp send through the AgentTask queue.

    The actual send happens later when the worker claims the task and the
    send-agent executor calls communication_service.send_whatsapp_to_lead.
    If USE_AGENT_TASK_QUEUE=0, dispatch falls back to synchronous direct
    send (legacy pre-Week-2 behavior).
    """
    from services.agent.dispatch_service import enqueue_send_whatsapp

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

    attempts = _channel_attempt_count(session, company_id, lead.id, "whatsapp")
    outcome = enqueue_send_whatsapp(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead.id,
        body=message,
        trigger=_ism_trigger(stage, attempts),
    )
    return _normalize_dispatch_outcome("whatsapp", outcome)


def _dispatch_email(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    stage: str,
) -> dict:
    """Enqueue an email send through the AgentTask queue. See _dispatch_whatsapp."""
    from services.agent.dispatch_service import enqueue_send_email

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

    attempts = _channel_attempt_count(session, company_id, lead.id, "email")
    outcome = enqueue_send_email(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead.id,
        subject=subject or _default_subject(lead, stage),
        body=body,
        trigger=_ism_trigger(stage, attempts),
    )
    return _normalize_dispatch_outcome("email", outcome)


def _normalize_dispatch_outcome(channel: str, outcome) -> dict:
    """Turn whatever enqueue_send_* returned into the stable ISM result shape.

    Queue path → outcome is an AgentTask (has .id, .status).
    Queue-off (feature flag) → outcome is the old send result dict or a Task
    depending on underlying service. Handle both.
    """
    if hasattr(outcome, "id") and hasattr(outcome, "status"):
        return {
            "channel": channel,
            "action": f"queued_send_{channel}",
            "agent_task_id": outcome.id,
            "status": outcome.status,
        }
    return {"channel": channel, "action": f"sent_{channel}", "result": outcome}


# Default (used when no template is configured)

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


# Stage transition logic

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


def _set_terminal_stage(lead: Lead, actor_user_id: int, session: Session, terminal: str) -> str:
    """Transition lead directly to a terminal stage (closed_won / closed_lost)."""
    lead.ism_stage = terminal
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()
    return terminal


def _decide_exhaustion_outcome(
    session: Session,
    company_id: int,
    lead: Lead,
) -> tuple[str, str]:
    """
    When all dispatch channels are exhausted, pick a terminal outcome based on
    customer-side signals collected so far.  No human in the loop unless
    signals genuinely conflict.

    Signals consulted:
      - Verbal CSAT rating from the call (Feedback rows, customer source).
      - Latest Quote status.
      - Future Appointment booked (demo).
      - Lead.qualification_status (set by post-call extractor).
      - Days since last outreach (silent ghost detector).

    Returns (decision, reason) where decision ∈ {"closed_won", "closed_lost", "handoff"}.
    """
    now = utc_now()
    pos_score = 0
    neg_score = 0
    reasons: list[str] = []

    # Verbal CSAT — strongest individual signal because it's customer voice.
    fb = session.exec(
        select(Feedback)
        .where(
            Feedback.company_id == company_id,
            Feedback.lead_id == lead.id,
            Feedback.source == "customer",
            Feedback.feedback_type == "csat",
            Feedback.rating.is_not(None),
        )
        .order_by(Feedback.created_at.desc())
        .limit(1)
    ).first()
    if fb and fb.rating is not None:
        if fb.rating >= 4:
            pos_score += 2
            reasons.append(f"verbal_csat={fb.rating}")
        elif fb.rating <= 2:
            neg_score += 2
            reasons.append(f"verbal_csat={fb.rating}")

    # Future appointment / demo booked = strong commit-to-buy signal.
    appt = session.exec(
        select(Appointment)
        .where(
            Appointment.company_id == company_id,
            Appointment.lead_id == lead.id,
            Appointment.appointment_time > now,
            Appointment.status.in_(["scheduled", "confirmed"]),
        )
        .limit(1)
    ).first()
    if appt:
        pos_score += 1
        reasons.append("future_demo_booked")

    # Latest quote status.
    quote = session.exec(
        select(Quote)
        .where(Quote.company_id == company_id, Quote.lead_id == lead.id)
        .order_by(Quote.id.desc())
        .limit(1)
    ).first()
    if quote:
        qstatus = (quote.status or "").lower()
        if qstatus == "accepted":
            pos_score += 2
            reasons.append("quote_accepted")
        elif qstatus in ("rejected", "expired"):
            neg_score += 1
            reasons.append(f"quote_{qstatus}")

    # Qualification verdict from post-call LLM extractor.
    qual = (lead.qualification_status or "").lower()
    if qual == "not_interested":
        neg_score += 2
        reasons.append("qualification=not_interested")
    elif qual in ("qualified", "proposal"):
        pos_score += 1
        reasons.append(f"qualification={qual}")

    # Silent ghost: no outreach activity for a long time AND no positive signal —
    # the customer simply went dark.  Default to closed_lost so the queue doesn't
    # hold stale leads forever.
    silent_days: int | None = None
    if lead.last_outreach_at:
        silent_days = (now - lead.last_outreach_at).days

    # Decision.  Require a clear winner; ties go to handoff so a human breaks them.
    if pos_score >= 2 and pos_score > neg_score:
        return "closed_won", ",".join(reasons) or "positive_signals"
    if neg_score >= 2 and neg_score > pos_score:
        return "closed_lost", ",".join(reasons) or "negative_signals"
    if silent_days is not None and silent_days >= 14 and pos_score == 0:
        return "closed_lost", f"silent_{silent_days}d"
    if pos_score == 0 and neg_score == 0:
        # No signals at all — customer never engaged after first touch.
        # Treat as closed_lost rather than parking forever.
        return "closed_lost", "no_engagement_signals"
    return "handoff", ",".join(reasons) or "ambiguous_signals"


def _update_lead_after_dispatch(
    session: Session,
    lead: Lead,
    actor_user_id: int,
    channel: str,
    stage: str,
) -> None:
    """Stamp outreach metadata back onto the lead row.

    Note: the pre-Week-3 code here also set `lead.last_outreach_channel`, but
    that field was never defined on the Lead model — Pydantic would have
    raised. Removed. If per-channel last-attempt is needed later, add the
    field to Lead via Alembic migration and re-introduce the write.
    """
    lead.last_outreach_at = utc_now()
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


# Public entry-point

ISMResult = dict


_VALID_DISPATCH_CHANNELS: frozenset[str] = frozenset({"call", "whatsapp", "email"})


def _execute_rule_action(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead: Lead,
    stage: str,
    rule,
) -> tuple[bool, Optional[str], Optional[str]]:
    """Execute a matched IsmRule's action.

    Returns (handled, forced_channel, skip_reason):
      - handled=True: the rule fully handled this cycle; caller should return
        immediately with the rule metadata appended to the result dict.
        skip_reason (if non-None) indicates why no dispatch happened.
      - handled=False: the rule requested a channel override only; the caller
        should continue with forced_channel as if _pick_channel returned it.
      - handled=False, forced_channel=None: rule action was 'skip' or
        unrecognized — caller falls through to normal _pick_channel.
    """
    from agents.ism_rules_engine import parse_action
    verb, arg = parse_action(rule.then_action)

    if verb == "advance_to":
        if not arg or arg not in ISM_STAGE_ORDER:
            logger.warning("[ism_rules] rule %s has invalid advance_to:%r — falling through", rule.id, arg)
            return (False, None, None)
        lead.ism_stage = arg
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead); session.commit()
        return (True, None, "rule_advanced_stage")

    if verb == "dispatch":
        if arg in _VALID_DISPATCH_CHANNELS:
            # Override the channel choice — caller continues with this channel
            return (False, arg, None)
        # dispatch:send_quote, dispatch:send_email, etc. Not yet supported
        # here (needs template/content) — fall through to default picker so
        # the rule doesn't silently do nothing.
        logger.debug("[ism_rules] rule %s dispatch:%s not directly supported, falling through", rule.id, arg)
        return (False, None, None)

    if verb == "handoff_to_human":
        # Create an approval-required task the operator will see in the inbox.
        # No executor is registered for task_type='handoff' so it stays in
        # `awaiting_approval` until an operator approves/rejects.
        try:
            from services.agent.agent_task_service import create_agent_task
            import hashlib
            # One handoff per (lead, stage) — dedupe if ISM re-tries
            key = hashlib.sha256(f"handoff:{lead.id}:{stage}:{rule.id}".encode()).hexdigest()[:40]
            create_agent_task(
                session=session,
                company_id=company_id,
                lead_id=lead.id,
                task_type="handoff",
                assigned_agent="webhook_sink",   # no-op executor; task completes on approve
                input_json={
                    "task_type": "handoff",
                    "reason": rule.name,
                    "rule_id": rule.id,
                    "stage": stage,
                    "summary": f"Handoff lead {lead.id} at stage '{stage}' — rule: {rule.name}",
                },
                idempotency_key=f"handoff:{lead.id}:{key}",
                requires_approval=True,
                actor_user_id=actor_user_id,
            )
        except Exception as exc:
            logger.warning("[ism_rules] failed to create handoff task for lead %s: %s", lead.id, exc)
        return (True, None, "rule_handoff_to_human")

    if verb == "skip":
        return (True, None, "rule_action_skip")

    logger.warning("[ism_rules] rule %s has unknown action verb %r — falling through", rule.id, verb)
    return (False, None, None)


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
            "rule_id": 5,                # if a rule fired (Week 3.3)
            "rule_name": "vip_budget",   # if a rule fired
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

    # Skip soft-deleted leads — no dispatch, no auto-close, no handoff,
    # no activity event.  A deleted lead must not influence anything
    # downstream (analytics, CSAT, billing, kanban).
    if lead.deleted_at is not None:
        return {"lead_id": lead_id, "skipped": True, "skip_reason": "lead_deleted"}

    stage = lead.ism_stage or "new"

    # Skip terminal / DNC leads.
    if stage in _TERMINAL_STAGES:
        return {"lead_id": lead_id, "stage": stage, "skipped": True, "skip_reason": "terminal_stage"}

    # Global cooldown: don't outreach if we already did within the tightest window.
    if lead.last_outreach_at:
        min_cooldown = min(_CHANNEL_COOLDOWN_HOURS.values())
        if utc_now() < lead.last_outreach_at + timedelta(hours=min_cooldown):
            return {"lead_id": lead_id, "stage": stage, "skipped": True, "skip_reason": "global_cooldown"}

    # Rules engine (Week 3.3) — data-driven overrides.
    forced_channel: Optional[str] = None
    matched_rule = None
    try:
        from agents.ism_rules_engine import evaluate_rules
        matched_rule = evaluate_rules(session, company_id, lead)
    except Exception as exc:
        logger.warning("[ism_rules] evaluation failed for lead=%s: %s", lead_id, exc)

    if matched_rule is not None:
        handled, forced_channel, skip_reason = _execute_rule_action(
            session, company_id, actor_user_id, lead, stage, matched_rule,
        )
        if handled:
            return {
                "lead_id": lead_id,
                "stage": stage,
                "skipped": True,
                "skip_reason": skip_reason,
                "rule_id": matched_rule.id,
                "rule_name": matched_rule.name,
            }

    # Pick best available channel (rule-forced if matched).
    if forced_channel is not None and _lead_has_channel(lead, forced_channel) \
       and not is_lead_opted_out(session, company_id, lead.id, forced_channel) \
       and not _is_channel_exhausted(session, company_id, lead.id, forced_channel) \
       and not _is_channel_in_cooldown(session, company_id, lead.id, forced_channel):
        channel = forced_channel
    else:
        channel = _pick_channel(session, company_id, lead, stage)
    if channel is None:
        # All dispatchable channels exhausted.  Decide the outcome from
        # customer-side signals (verbal CSAT, quote status, appointment,
        # qualification, silence duration).  Only fall back to a human
        # handoff when signals genuinely conflict — automation-first.
        decision, reason = _decide_exhaustion_outcome(session, company_id, lead)

        if decision in ("closed_won", "closed_lost"):
            new_stage = _set_terminal_stage(lead, actor_user_id, session, decision)
            logger.info(
                "ISM: lead=%d channels exhausted at stage=%s → auto-%s (signals: %s)",
                lead_id, stage, new_stage, reason,
            )
            try:
                from services.call import ism_broadcaster
                ism_broadcaster.publish(
                    company_id=company_id,
                    lead_id=lead_id,
                    lead_name=lead.name,
                    stage=new_stage,
                    action=f"auto_{decision}",
                    reason=f"channels exhausted at {stage}; signals: {reason}",
                )
            except Exception:  # noqa: BLE001
                pass
            return {
                "lead_id": lead_id,
                "stage": stage,
                "skipped": True,
                "skip_reason": "all_channels_blocked",
                "advanced_to_stage": new_stage,
                "decision_reason": reason,
            }

        # Genuinely ambiguous — emit handoff for human review.  Idempotency
        # key prevents flooding: one task per (lead, stage) while non-terminal.
        try:
            from services.agent.agent_task_service import create_agent_task
            create_agent_task(
                session=session,
                company_id=company_id,
                task_type="handoff",
                assigned_agent="closer",
                input_json={
                    "lead_id": lead_id,
                    "stage": stage,
                    "reason": "ambiguous_signals",
                    "signal_summary": reason,
                    "summary": f"Lead {lead_id} channels exhausted at stage={stage}; signals conflict ({reason}) — needs human review.",
                },
                lead_id=lead_id,
                actor_user_id=actor_user_id,
                idempotency_key=f"ism-exhausted:{lead_id}:{stage}",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("ISM: failed to create handoff task for lead=%d: %s", lead_id, exc)

        logger.info(
            "ISM: lead=%d channels exhausted at stage=%s → handoff (ambiguous: %s)",
            lead_id, stage, reason,
        )
        try:
            from services.call import ism_broadcaster
            ism_broadcaster.publish(
                company_id=company_id,
                lead_id=lead_id,
                lead_name=lead.name,
                stage=stage,
                action="handoff",
                reason=f"channels exhausted; ambiguous signals: {reason}",
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "lead_id": lead_id,
            "stage": stage,
            "skipped": True,
            "skip_reason": "all_channels_blocked",
            "handoff_created": True,
            "decision_reason": reason,
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
        try:
            from services.call import ism_broadcaster
            ism_broadcaster.publish(
                company_id=company_id,
                lead_id=lead_id,
                lead_name=lead.name,
                stage=stage,
                action="dispatch_failed",
                reason=f"{channel}: {exc}",
            )
        except Exception:  # noqa: BLE001
            pass
        return {
            "lead_id": lead_id,
            "stage": stage,
            "channel": channel,
            "skipped": True,
            "skip_reason": f"dispatch_error: {exc}",
        }

    # Live activity feed — publish a one-line summary the dashboard can render.
    try:
        from services.call import ism_broadcaster
        rule_note = f" (rule: {matched_rule.name})" if matched_rule else ""
        ism_broadcaster.publish(
            company_id=company_id,
            lead_id=lead_id,
            lead_name=lead.name,
            stage=stage,
            action=f"dispatched_{channel}",
            reason=f"stage={stage}{rule_note}",
            metadata={"channel": channel, "result": result},
        )
    except Exception:  # noqa: BLE001
        pass

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


# Batch runner — called by the automation worker

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
    # We also pre-filter on `last_outreach_at` to avoid loading thousands of rows when most are in cooldown — the tightest cooldown window is 6h (WhatsApp), so any lead outreached in the last 6h can be skipped here.
    min_cooldown_hours = min(_CHANNEL_COOLDOWN_HOURS.values())
    cutoff = utc_now() - timedelta(hours=min_cooldown_hours)

    leads = session.exec(
        select(Lead).where(
            Lead.company_id == company_id,
            Lead.deleted_at.is_(None),
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

    # Build a set of lead IDs that are actively enrolled in a running campaign so ISM doesn't double-process them.
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
