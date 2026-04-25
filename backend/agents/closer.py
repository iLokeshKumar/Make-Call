"""Closer agent — drives a sent quote toward close_won or handoff.

Week 7.3 of the roadmap. Procedural (no LangGraph) so the agent stays easy
to debug and cheap to iterate on while the free-tier Mistral budget is
tight.  If the logic ever wants to branch across more than one LLM call
per situation we can migrate to a StateGraph, but today's flow is:

    load_context   →   classify_situation   →   dispatch_per_classification

Triggered two ways:
  * Worker cycle enqueues `closer_followup` AgentTasks for quotes that
    have been silent ≥ 3 days (see automation_worker_service
    `_enqueue_closer_tasks_for_silent_quotes`).
  * Reply classifier enqueues on inbound `objection` / `question`
    intents when a Quote already exists.

Terminal outcomes:
  * `close_won` — `lead.ism_stage="closed_won"`, `qualification_status="won"`,
    `next_action="celebrate"`.
  * `handoff_to_human` — creates `AgentTask(task_type="handoff",
    requires_approval=True)` with a populated `negotiation_summary`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from database import engine
from models.models import (
    CompetitorMention,
    Interaction,
    Lead,
    ObjectionEntry,
    Quote,
    utc_now,
)

logger = logging.getLogger(__name__)


# Classification thresholds / heuristics

_STRONG_POSITIVE = (
    "yes, let's go", "let's go", "go ahead", "proceed", "send the contract",
    "looks good", "happy to sign", "sign me up", "accept", "works for us",
    "let's do it", "approved", "sold", "take my money", "ready to sign",
)

_OBJECTION_NEGATIVE = (
    "too expensive", "over budget", "pricey", "cheaper", "discount",
    "not now", "not right now", "later", "come back",
    "competitor", "alternative", "compared to",
    "concern", "worried", "not sure", "hesitant",
)

_CLEAR_QUESTION = ("?", " what ", " how ", " when ", " why ", " can you ", " could you ")

_MAX_NEGOTIATION_ROUNDS = 5
_STALE_QUOTE_STATUSES = {"accepted", "rejected", "expired", "draft"}
_ACTIVE_QUOTE_STATUSES = {"sent", "opened", "negotiation"}


def _coerce_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _load_context(
    session: Session,
    company_id: int,
    lead_id: int,
    quote_id: int,
) -> dict[str, Any] | None:
    """Load the lead, quote, objections, competitor mentions, and inbound
    replies since the quote was sent.

    Returns None if any core record is missing or stale.
    """
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
            Lead.deleted_at.is_(None),
        )
    ).first()
    if lead is None:
        return None

    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == company_id,
            Quote.deleted_at.is_(None),
        )
    ).first()
    if quote is None:
        return None

    objections = session.exec(
        select(ObjectionEntry).where(
            ObjectionEntry.company_id == company_id,
            ObjectionEntry.is_active == True,  # noqa: E712
        ).order_by(ObjectionEntry.frequency_count.desc()).limit(10)
    ).all()

    competitors = session.exec(
        select(CompetitorMention).where(
            CompetitorMention.company_id == company_id,
            CompetitorMention.lead_id == lead_id,
        ).order_by(CompetitorMention.created_at.desc()).limit(10)
    ).all()

    sent_at = _coerce_utc(quote.sent_at)
    recent_inbound: list[Interaction] = []
    if sent_at is not None:
        recent_inbound = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead_id,
                Interaction.direction == "inbound",
                Interaction.started_at > sent_at,
            ).order_by(Interaction.started_at.desc()).limit(10)
        ).all()

    return {
        "lead": lead,
        "quote": quote,
        "objections": list(objections),
        "competitors": list(competitors),
        "recent_inbound": list(recent_inbound),
    }


def _classify_situation(ctx: dict[str, Any]) -> str:
    """Rule-based bucket: silent | replied_objection | replied_question | ready_to_close.

    Keeps the common case off the LLM path entirely.  An inbound message only
    hits the LLM when none of the obvious keyword tells trigger — and the
    cycle cap still applies (see the reply classifier).
    """
    recent_inbound: list[Interaction] = ctx.get("recent_inbound") or []
    if not recent_inbound:
        return "silent"

    latest_body = ""
    for interaction in recent_inbound:
        body = ""
        if interaction.content:
            body = interaction.content
        elif interaction.metadata_json and isinstance(interaction.metadata_json, dict):
            body = str(interaction.metadata_json.get("body") or "")
        if body:
            latest_body = body.lower()
            break

    if not latest_body:
        return "silent"

    if any(term in latest_body for term in _STRONG_POSITIVE):
        return "ready_to_close"
    if any(term in latest_body for term in _OBJECTION_NEGATIVE):
        return "replied_objection"
    if any(marker in f" {latest_body} " for marker in _CLEAR_QUESTION):
        return "replied_question"

    return "replied_question"


def _count_negotiation_rounds(ctx: dict[str, Any]) -> int:
    """Rough round count — each inbound reply is one 'round' of back-and-forth."""
    return len(ctx.get("recent_inbound") or [])


def _find_best_rebuttal(objections: list[ObjectionEntry], latest_body: str) -> ObjectionEntry | None:
    """Pick the ObjectionEntry whose key or text overlaps the reply body.

    Falls back to the most-frequent objection with a non-empty rebuttal when
    no keyword matches, because ObjectionEntry.rebuttal is edited by admins
    and the most common objection's rebuttal is usually generic enough.
    """
    if not objections:
        return None
    lowered = (latest_body or "").lower()
    for obj in objections:
        key = (obj.objection_key or "").lower()
        text = (obj.objection_text or "").lower()
        if key and key in lowered:
            return obj
        if text and text in lowered:
            return obj
    for obj in objections:
        if obj.rebuttal:
            return obj
    return None


def _first_inbound_body(ctx: dict[str, Any]) -> str:
    recent: list[Interaction] = ctx.get("recent_inbound") or []
    for interaction in recent:
        if interaction.content:
            return interaction.content
        meta = interaction.metadata_json or {}
        if isinstance(meta, dict) and meta.get("body"):
            return str(meta["body"])
    return ""


def _generate_followup_body(lead: Lead, quote: Quote, silence_days: int) -> str:
    """Cheap default follow-up body — no LLM, no template render.

    Keeps the closer functional even when Mistral is rate-limited and the
    template engine isn't configured for this company.  Companies can
    override by setting a closer-specific template id; that lands in a
    follow-up PR.
    """
    name = (lead.name or "there").split()[0]
    return (
        f"Hi {name},\n\n"
        f"Just circling back on quotation {quote.quote_number}. It's been {silence_days} "
        f"day(s) and I wanted to check whether you had any questions or needed "
        f"anything clarified before moving forward.\n\n"
        f"Happy to hop on a quick call if that would help.\n\n"
        f"Thanks,\nRio"
    )


def _parry_body(lead: Lead, quote: Quote, rebuttal: str | None) -> str:
    name = (lead.name or "there").split()[0]
    fallback = "Happy to address that — here's how we think about it, and let me know if more detail helps."
    return (
        f"Hi {name},\n\n"
        f"Thanks for raising that on {quote.quote_number}.\n\n"
        f"{rebuttal or fallback}\n\n"
        f"Thanks,\nRio"
    )


def _answer_body(lead: Lead, quote: Quote, question: str) -> str:
    name = (lead.name or "there").split()[0]
    return (
        f"Hi {name},\n\n"
        f"Thanks for the question about {quote.quote_number}.\n\n"
        f"You asked: \"{question.strip()[:300]}\"\n\n"
        f"I'll get back to you shortly with a precise answer — one of our team "
        f"will review and send a tailored reply.\n\n"
        f"Thanks,\nRio"
    )


def _negotiation_summary(ctx: dict[str, Any], reason: str) -> str:
    lead: Lead = ctx["lead"]
    quote: Quote = ctx["quote"]
    rounds = _count_negotiation_rounds(ctx)
    latest_body = _first_inbound_body(ctx)
    latest_excerpt = (latest_body[:240] + "…") if len(latest_body) > 240 else latest_body
    return (
        f"Lead {lead.id} ({lead.name or 'unknown'}) on quote {quote.quote_number}\n"
        f"Reason: {reason}\n"
        f"Rounds observed: {rounds}\n"
        f"Last inbound excerpt: {latest_excerpt or '(none)'}"
    )


def _dispatch_closer_action(
    session: Session,
    company_id: int,
    actor_user_id: int,
    ctx: dict[str, Any],
    classification: str,
    silence_days: int,
) -> dict[str, Any]:
    """Turn the classification into the appropriate next action.

    `silent` / `replied_objection` / `replied_question` → enqueue a send_email
    task (which the default approval gate escalates to human review when the
    company's approval policy says so — the closer itself doesn't bypass it).

    `ready_to_close` → advance the lead if the deal looks closable, else
    escalate via handoff.
    """
    from services.agent.agent_task_service import create_agent_task

    lead: Lead = ctx["lead"]
    quote: Quote = ctx["quote"]

    if classification == "silent":
        body = _generate_followup_body(lead, quote, silence_days)
        task = create_agent_task(
            session=session,
            company_id=company_id,
            task_type="send_email",
            assigned_agent="send",
            input_json={
                "lead_id": lead.id,
                "subject": f"Following up on {quote.quote_number}",
                "body": body,
                "trigger": f"closer:silent:{quote.id}:{silence_days}",
            },
            lead_id=lead.id,
            idempotency_key=f"closer_silent:{quote.id}:{silence_days}",
            actor_user_id=actor_user_id,
        )
        return {"outcome": "followup_sent", "classification": classification, "task_id": task.id}

    if classification == "replied_objection":
        rebuttal = _find_best_rebuttal(ctx.get("objections") or [], _first_inbound_body(ctx))
        body = _parry_body(lead, quote, rebuttal.rebuttal if rebuttal else None)
        task = create_agent_task(
            session=session,
            company_id=company_id,
            task_type="send_email",
            assigned_agent="send",
            input_json={
                "lead_id": lead.id,
                "subject": f"Re: {quote.quote_number}",
                "body": body,
                "objection_id": rebuttal.id if rebuttal else None,
                "trigger": f"closer:parry:{quote.id}",
            },
            lead_id=lead.id,
            idempotency_key=f"closer_parry:{quote.id}:{rebuttal.id if rebuttal else 'fallback'}",
            actor_user_id=actor_user_id,
        )
        return {
            "outcome": "objection_parried",
            "classification": classification,
            "task_id": task.id,
            "rebuttal_id": rebuttal.id if rebuttal else None,
        }

    if classification == "replied_question":
        body = _answer_body(lead, quote, _first_inbound_body(ctx))
        task = create_agent_task(
            session=session,
            company_id=company_id,
            task_type="send_email",
            assigned_agent="send",
            input_json={
                "lead_id": lead.id,
                "subject": f"Re: {quote.quote_number}",
                "body": body,
                "trigger": f"closer:answer:{quote.id}",
            },
            lead_id=lead.id,
            idempotency_key=f"closer_answer:{quote.id}:{hash(_first_inbound_body(ctx)[:200]) % 10_000_000}",
            actor_user_id=actor_user_id,
        )
        return {"outcome": "question_answered", "classification": classification, "task_id": task.id}

    # ready_to_close path — advance if not stuck, else handoff
    rounds = _count_negotiation_rounds(ctx)
    if rounds <= _MAX_NEGOTIATION_ROUNDS:
        lead.ism_stage = "closed_won"
        lead.qualification_status = "won"
        lead.next_action = "celebrate"
        lead.next_action_due_at = None
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        # Flip the quote to accepted so stale checks on re-runs dedupe cleanly.
        quote.status = "accepted"
        quote.accepted_at = utc_now()
        quote.updated_at = utc_now()
        quote.updated_by = actor_user_id
        session.add(quote)
        session.commit()
        return {
            "outcome": "close_won",
            "classification": classification,
            "quote_id": quote.id,
            "rounds": rounds,
        }

    # Too many rounds — escalate
    summary = _negotiation_summary(ctx, reason=f"stuck after {rounds} rounds")
    task = create_agent_task(
        session=session,
        company_id=company_id,
        task_type="handoff",
        assigned_agent="send",
        input_json={
            "reason": f"stuck after {rounds} negotiation rounds",
            "negotiation_summary": summary,
            "lead_id": lead.id,
            "quote_id": quote.id,
        },
        lead_id=lead.id,
        idempotency_key=f"closer_handoff:{quote.id}",
        requires_approval=True,
        actor_user_id=actor_user_id,
    )
    return {
        "outcome": "handoff_to_human",
        "classification": classification,
        "task_id": task.id,
        "rounds": rounds,
    }


async def run(
    company_id: int,
    actor_user_id: int,
    lead_id: int | None = None,
    quote_id: int | None = None,
    silence_days: int = 0,
    **_kwargs: Any,
) -> dict[str, Any]:
    """Closer entry point matching the orchestrator.run_agent convention.

    Worker enqueues `closer_followup` tasks with `input_json = {lead_id,
    quote_id, silence_days}`; the worker dispatcher unpacks that into kwargs
    and calls this function.
    """
    if not lead_id or not quote_id:
        return {"error": "lead_id and quote_id required", "skipped": True}

    with Session(engine) as session:
        ctx = _load_context(session, company_id, lead_id, quote_id)
        if ctx is None:
            return {"skipped": True, "reason": "context_not_found", "quote_id": quote_id}

        quote: Quote = ctx["quote"]
        if (quote.status or "") in _STALE_QUOTE_STATUSES:
            return {"skipped": True, "reason": "quote_resolved", "quote_id": quote_id}
        if (quote.status or "") not in _ACTIVE_QUOTE_STATUSES:
            # Unknown status — play it safe.
            return {"skipped": True, "reason": f"quote_status_{quote.status}", "quote_id": quote_id}

        lead: Lead = ctx["lead"]
        if (lead.ism_stage or "") in {"closed_won", "closed_lost", "nurture_pause"}:
            return {
                "skipped": True,
                "reason": f"lead_stage_{lead.ism_stage}",
                "quote_id": quote_id,
            }

        classification = _classify_situation(ctx)
        return _dispatch_closer_action(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            ctx=ctx,
            classification=classification,
            silence_days=silence_days,
        )
