"""
Service Agent — Auto triage, ticket creation, SLA routing, customer updates, CSAT loop.

Actions:
  triage          — Analyze description, auto-categorize, create ticket
  create_ticket   — Create a ServiceTicket with SLA hours computed from priority
  update_customer — Send a status update to the lead via an Interaction record
  close_ticket    — Set ServiceTicket.status = "closed"
  send_csat       — Create Feedback (csat) and return CSAT link placeholder
  check_sla       — Find and escalate SLA-breaching open tickets
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlmodel import Session, select

from models.models import (
    AgentTask,
    Feedback,
    Interaction,
    ServiceTicket,
    utc_now,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SLA hours by priority
# ---------------------------------------------------------------------------
_SLA_HOURS: dict[str, int] = {
    "critical": 4,
    "high": 8,
    "medium": 24,
    "low": 72,
}

_OPEN_STATUSES = {"open", "in_progress", "pending_customer", "pending_parts"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _generate_ticket_number(session: Session, company_id: int) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"TKT-{year}-"
    tickets = session.exec(
        select(ServiceTicket).where(ServiceTicket.company_id == company_id)
    ).all()
    max_seq = 0
    for t in tickets:
        if t.ticket_number.startswith(prefix):
            try:
                seq = int(t.ticket_number[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                pass
    return f"{prefix}{max_seq + 1:04d}"


def _infer_category(description: str) -> str:
    desc_lower = (description or "").lower()
    if "install" in desc_lower:
        return "installation"
    if "bill" in desc_lower or "payment" in desc_lower:
        return "billing"
    if "broken" in desc_lower or "not working" in desc_lower:
        return "maintenance"
    return "general"


def _infer_priority(description: str) -> str:
    desc_lower = (description or "").lower()
    if "urgent" in desc_lower or "critical" in desc_lower:
        return "high"
    return "medium"


def _create_ticket(
    session: Session,
    company_id: int,
    lead_id: int | None,
    order_id: int | None,
    title: str,
    description: str | None,
    priority: str,
    category: str,
) -> ServiceTicket:
    from datetime import timedelta

    sla_hours = _SLA_HOURS.get(priority, 24)
    now = utc_now()
    ticket = ServiceTicket(
        company_id=company_id,
        lead_id=lead_id,
        order_id=order_id,
        ticket_number=_generate_ticket_number(session, company_id),
        title=title,
        description=description,
        status="open",
        priority=priority,
        category=category,
        channel="manual",
        sla_hours=sla_hours,
        sla_due_at=now + timedelta(hours=sla_hours),
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_triage(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    description = inp.get("description", "")
    lead_id = inp.get("lead_id")
    order_id = inp.get("order_id")

    if not description:
        return {"error": "description is required for triage"}

    category = _infer_category(description)
    priority = _infer_priority(description)
    title = inp.get("title") or f"Triage: {description[:80]}"

    ticket = _create_ticket(
        session,
        company_id=task.company_id,
        lead_id=lead_id,
        order_id=order_id,
        title=title,
        description=description,
        priority=priority,
        category=category,
    )
    logger.info("[ServiceAgent] Triaged ticket %s (cat=%s pri=%s)", ticket.ticket_number, category, priority)
    return {
        "action": "triage",
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "category": category,
        "priority": priority,
        "sla_hours": ticket.sla_hours,
    }


def _handle_create_ticket(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    title = inp.get("title")
    if not title:
        return {"error": "title is required for create_ticket"}

    priority = inp.get("priority", "medium")
    category = inp.get("category", "general")
    lead_id = inp.get("lead_id")
    order_id = inp.get("order_id")
    description = inp.get("description")

    ticket = _create_ticket(
        session,
        company_id=task.company_id,
        lead_id=lead_id,
        order_id=order_id,
        title=title,
        description=description,
        priority=priority,
        category=category,
    )
    logger.info("[ServiceAgent] Created ticket %s", ticket.ticket_number)
    return {
        "action": "create_ticket",
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "priority": ticket.priority,
        "category": ticket.category,
        "sla_hours": ticket.sla_hours,
        "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
    }


def _handle_update_customer(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    lead_id = inp.get("lead_id")
    ticket_id = inp.get("ticket_id")

    if not lead_id:
        return {"error": "lead_id is required for update_customer"}

    ticket_ref = f" (ticket #{ticket_id})" if ticket_id else ""
    content = inp.get("content") or f"Status update on your service request{ticket_ref}."

    interaction = Interaction(
        company_id=task.company_id,
        lead_id=lead_id,
        type="service_update",
        channel="email",
        direction="outbound",
        source="service_agent",
        content=content,
        started_at=utc_now(),
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)
    logger.info("[ServiceAgent] Customer update sent for lead %s (interaction %s)", lead_id, interaction.id)
    return {
        "action": "update_customer",
        "interaction_id": interaction.id,
        "lead_id": lead_id,
    }


def _handle_close_ticket(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    ticket_id = inp.get("ticket_id")
    if not ticket_id:
        return {"error": "ticket_id is required for close_ticket"}

    ticket = session.exec(
        select(ServiceTicket).where(
            ServiceTicket.id == ticket_id,
            ServiceTicket.company_id == task.company_id,
        )
    ).first()
    if not ticket:
        return {"error": f"ServiceTicket {ticket_id} not found"}

    ticket.status = "closed"
    ticket.closed_at = utc_now()
    session.add(ticket)
    session.commit()
    logger.info("[ServiceAgent] Closed ticket %s", ticket.ticket_number)
    return {
        "action": "close_ticket",
        "ticket_id": ticket.id,
        "ticket_number": ticket.ticket_number,
        "closed_at": ticket.closed_at.isoformat(),
    }


def _handle_send_csat(session: Session, task: AgentTask) -> dict:
    inp = task.input_json
    ticket_id = inp.get("ticket_id")
    lead_id = inp.get("lead_id")
    interaction_id = inp.get("interaction_id")

    if not ticket_id and not lead_id:
        return {"error": "ticket_id or lead_id is required for send_csat"}

    # Resolve lead_id from ticket if not supplied
    if not lead_id and ticket_id:
        ticket = session.exec(
            select(ServiceTicket).where(
                ServiceTicket.id == ticket_id,
                ServiceTicket.company_id == task.company_id,
            )
        ).first()
        if ticket:
            lead_id = ticket.lead_id

    import uuid
    token = uuid.uuid4().hex

    feedback = Feedback(
        company_id=task.company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        feedback_type="csat",
        source="customer",
        status="pending",
        token=token,
    )
    session.add(feedback)
    session.commit()
    session.refresh(feedback)

    csat_link = f"https://app.example.com/feedback/{token}"
    logger.info("[ServiceAgent] CSAT record %s created for lead %s", feedback.id, lead_id)
    return {
        "action": "send_csat",
        "feedback_id": feedback.id,
        "csat_link": csat_link,
        "lead_id": lead_id,
    }


def _handle_check_sla(session: Session, task: AgentTask) -> dict:
    now = utc_now()
    breaching = session.exec(
        select(ServiceTicket).where(
            ServiceTicket.company_id == task.company_id,
            ServiceTicket.status.in_(list(_OPEN_STATUSES)),
            ServiceTicket.sla_due_at <= now,
        )
    ).all()

    escalated_ids = []
    for ticket in breaching:
        ticket.status = "escalated"
        session.add(ticket)
        escalated_ids.append(ticket.id)

    if escalated_ids:
        session.commit()

    logger.info("[ServiceAgent] SLA check escalated %d tickets", len(escalated_ids))
    return {
        "action": "check_sla",
        "breaching_ticket_ids": escalated_ids,
        "escalated_count": len(escalated_ids),
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run(session: Session, task: AgentTask) -> dict:
    """Dispatch to the appropriate service agent action."""
    action = task.input_json.get("action")
    try:
        if action == "triage":
            return _handle_triage(session, task)
        elif action == "create_ticket":
            return _handle_create_ticket(session, task)
        elif action == "update_customer":
            return _handle_update_customer(session, task)
        elif action == "close_ticket":
            return _handle_close_ticket(session, task)
        elif action == "send_csat":
            return _handle_send_csat(session, task)
        elif action == "check_sla":
            return _handle_check_sla(session, task)
        else:
            return {
                "error": f"Unknown action: {action!r}",
                "valid_actions": ["triage", "create_ticket", "update_customer", "close_ticket", "send_csat", "check_sla"],
            }
    except Exception as exc:
        logger.exception("[ServiceAgent] action=%s failed: %s", action, exc)
        return {"error": str(exc), "action": action}
