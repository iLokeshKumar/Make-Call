from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import (
    ServiceTicketCreate,
    TicketCommentCreate,
    User,
)
from services.service.ticket_service import (
    add_comment,
    assign_ticket,
    check_sla_breaches,
    create_ticket,
    get_ticket_or_404,
    list_comments,
    list_tickets,
    record_csat,
    update_ticket_status,
)

router = APIRouter(prefix="/tickets", tags=["Service Tickets"])


@router.post("")
async def create_ticket_route(
    data: ServiceTicketCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.manage")),
):
    return create_ticket(session, current_user.company_id, current_user.id, data)


@router.get("")
async def list_tickets_route(
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
    assignee_user_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.read")),
):
    return list_tickets(
        session,
        current_user.company_id,
        status=status,
        lead_id=lead_id,
        assignee_user_id=assignee_user_id,
    )


@router.get("/{ticket_id}")
async def get_ticket_route(
    ticket_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.read")),
):
    return get_ticket_or_404(session, current_user.company_id, ticket_id)


class TicketStatusUpdate:
    def __init__(self, status: str, notes: Optional[str] = None):
        self.status = status
        self.notes = notes


from pydantic import BaseModel


class TicketStatusBody(BaseModel):
    status: str
    notes: Optional[str] = None


class TicketAssignBody(BaseModel):
    assignee_user_id: int


class TicketCsatBody(BaseModel):
    score: int
    comment: Optional[str] = None


@router.patch("/{ticket_id}/status")
async def update_ticket_status_route(
    ticket_id: int,
    body: TicketStatusBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.manage")),
):
    return update_ticket_status(
        session,
        current_user.company_id,
        current_user.id,
        ticket_id,
        body.status,
        body.notes,
    )


@router.patch("/{ticket_id}/assign")
async def assign_ticket_route(
    ticket_id: int,
    body: TicketAssignBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.manage")),
):
    return assign_ticket(
        session,
        current_user.company_id,
        current_user.id,
        ticket_id,
        body.assignee_user_id,
    )


@router.post("/{ticket_id}/comments")
async def add_comment_route(
    ticket_id: int,
    data: TicketCommentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.manage")),
):
    return add_comment(
        session,
        current_user.company_id,
        current_user.id,
        ticket_id,
        data,
    )


@router.get("/{ticket_id}/comments")
async def list_comments_route(
    ticket_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.read")),
):
    return list_comments(session, current_user.company_id, ticket_id)


@router.post("/{ticket_id}/csat")
async def record_csat_route(
    ticket_id: int,
    body: TicketCsatBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("ticket.manage")),
):
    return record_csat(
        session,
        current_user.company_id,
        ticket_id,
        body.score,
        body.comment,
    )
