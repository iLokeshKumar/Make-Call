from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    EventStore,
    ServiceTicket,
    ServiceTicketCreate,
    TicketComment,
    TicketCommentCreate,
    utc_now,
)

logger = logging.getLogger(__name__)

VALID_STATUSES = {
    "open",
    "in_progress",
    "pending_customer",
    "pending_parts",
    "resolved",
    "closed",
    "escalated",
}

# Statuses that indicate work has started (triggers first_response_at)
_NON_OPEN_STATUSES = VALID_STATUSES - {"open"}


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


def _emit_event(
    session: Session,
    company_id: int,
    actor_user_id: int,
    event_type: str,
    ticket_id: int,
    payload: dict,
) -> None:
    try:
        event = EventStore(
            company_id=company_id,
            event_type=event_type,
            aggregate_type="ticket",
            aggregate_id=ticket_id,
            correlation_id=str(uuid4()),
            payload=payload,
            actor_user_id=actor_user_id,
        )
        session.add(event)
        session.commit()
    except Exception as exc:
        logger.warning("[TicketService] EventStore emit failed: %s", exc)


def create_ticket(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: ServiceTicketCreate,
) -> ServiceTicket:
    now = utc_now()
    ticket = ServiceTicket(
        company_id=company_id,
        lead_id=data.lead_id,
        account_id=data.account_id,
        order_id=data.order_id,
        ticket_number=_generate_ticket_number(session, company_id),
        title=data.title,
        description=data.description,
        status="open",
        priority=data.priority,
        category=data.category,
        channel=data.channel,
        sla_hours=data.sla_hours,
        sla_due_at=now + timedelta(hours=data.sla_hours),
        created_by=actor_user_id,
        updated_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(ticket)
    session.commit()
    session.refresh(ticket)

    _emit_event(
        session,
        company_id,
        actor_user_id,
        "ticket.opened",
        ticket.id,
        {"ticket_number": ticket.ticket_number, "title": ticket.title},
    )
    return ticket


def get_ticket_or_404(session: Session, company_id: int, ticket_id: int) -> ServiceTicket:
    ticket = session.exec(
        select(ServiceTicket).where(
            ServiceTicket.id == ticket_id,
            ServiceTicket.company_id == company_id,
        )
    ).first()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


def list_tickets(
    session: Session,
    company_id: int,
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
    assignee_user_id: Optional[int] = None,
) -> list[ServiceTicket]:
    query = select(ServiceTicket).where(ServiceTicket.company_id == company_id)
    if status:
        query = query.where(ServiceTicket.status == status)
    if lead_id:
        query = query.where(ServiceTicket.lead_id == lead_id)
    if assignee_user_id:
        query = query.where(ServiceTicket.assignee_user_id == assignee_user_id)
    return session.exec(query.order_by(ServiceTicket.created_at.desc())).all()


def update_ticket_status(
    session: Session,
    company_id: int,
    actor_user_id: int,
    ticket_id: int,
    status: str,
    notes: Optional[str] = None,
) -> ServiceTicket:
    if status not in VALID_STATUSES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}",
        )

    ticket = get_ticket_or_404(session, company_id, ticket_id)
    old_status = ticket.status
    now = utc_now()

    ticket.status = status
    ticket.updated_at = now
    ticket.updated_by = actor_user_id

    # Set first_response_at on the first transition away from "open"
    if status in _NON_OPEN_STATUSES and ticket.first_response_at is None:
        ticket.first_response_at = now

    if status == "resolved" and ticket.resolved_at is None:
        ticket.resolved_at = now

    if status == "closed" and ticket.closed_at is None:
        ticket.closed_at = now

    session.add(ticket)
    session.commit()
    session.refresh(ticket)

    _emit_event(
        session,
        company_id,
        actor_user_id,
        f"ticket.status_changed",
        ticket.id,
        {
            "old_status": old_status,
            "new_status": status,
            "notes": notes,
        },
    )
    return ticket


def assign_ticket(
    session: Session,
    company_id: int,
    actor_user_id: int,
    ticket_id: int,
    assignee_user_id: int,
) -> ServiceTicket:
    ticket = get_ticket_or_404(session, company_id, ticket_id)
    ticket.assignee_user_id = assignee_user_id
    ticket.updated_at = utc_now()
    ticket.updated_by = actor_user_id
    session.add(ticket)
    session.commit()
    session.refresh(ticket)

    _emit_event(
        session,
        company_id,
        actor_user_id,
        "ticket.assigned",
        ticket.id,
        {"assignee_user_id": assignee_user_id},
    )
    return ticket


def add_comment(
    session: Session,
    company_id: int,
    actor_user_id: int,
    ticket_id: int,
    data: TicketCommentCreate,
) -> TicketComment:
    # Verify ticket belongs to company
    get_ticket_or_404(session, company_id, ticket_id)

    now = utc_now()
    comment = TicketComment(
        company_id=company_id,
        ticket_id=ticket_id,
        author_user_id=actor_user_id,
        body=data.body,
        is_internal=data.is_internal,
        created_by=actor_user_id,
        updated_by=actor_user_id,
        created_at=now,
        updated_at=now,
    )
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


def list_comments(
    session: Session,
    company_id: int,
    ticket_id: int,
) -> list[TicketComment]:
    # Verify ticket belongs to company
    get_ticket_or_404(session, company_id, ticket_id)

    return session.exec(
        select(TicketComment)
        .where(
            TicketComment.ticket_id == ticket_id,
            TicketComment.company_id == company_id,
        )
        .order_by(TicketComment.created_at.asc())
    ).all()


def check_sla_breaches(session: Session, company_id: int) -> int:
    """Find open/in_progress tickets past sla_due_at and escalate them. Returns count escalated."""
    now = utc_now()
    breached = session.exec(
        select(ServiceTicket).where(
            ServiceTicket.company_id == company_id,
            ServiceTicket.status.in_(["open", "in_progress"]),
            ServiceTicket.sla_due_at <= now,
        )
    ).all()

    count = 0
    for ticket in breached:
        old_status = ticket.status
        ticket.status = "escalated"
        ticket.updated_at = now
        session.add(ticket)
        count += 1

        _emit_event(
            session,
            company_id,
            0,  # system actor
            "ticket.sla_breached",
            ticket.id,
            {"old_status": old_status, "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None},
        )

    if count:
        session.commit()

    return count


def record_csat(
    session: Session,
    company_id: int,
    ticket_id: int,
    score: int,
    comment: Optional[str] = None,
) -> ServiceTicket:
    if not (1 <= score <= 5):
        raise HTTPException(status_code=400, detail="CSAT score must be between 1 and 5")

    ticket = get_ticket_or_404(session, company_id, ticket_id)
    ticket.csat_score = score
    ticket.csat_comment = comment
    ticket.updated_at = utc_now()
    session.add(ticket)
    session.commit()
    session.refresh(ticket)
    return ticket
