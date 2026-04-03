from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import Quote, QuoteCreate, User, QuoteSendRequest
from services.quote_service import (
    create_quote,
    generate_quote_pdf,
    get_quote_or_404,
    mark_quote_status,
)
from services.communication_service import send_quote_to_lead

router = APIRouter(prefix="/quotes", tags=["Quotes"])


@router.post("")
async def create_quote_route(
    data: QuoteCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    return create_quote(session, current_user.company_id, current_user.id, data)


@router.get("")
async def list_quotes_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.read")),
):
    return session.exec(
        select(Quote).where(
            Quote.company_id == current_user.company_id
        ).order_by(Quote.created_at.desc())
    ).all()


@router.get("/{quote_id}")
async def get_quote_route(
    quote_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.read")),
):
    return get_quote_or_404(session, current_user.company_id, quote_id)


@router.post("/{quote_id}/generate-pdf")
async def generate_quote_pdf_route(
    quote_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    return generate_quote_pdf(session, current_user.company_id, current_user.id, quote_id)


@router.post("/{quote_id}/send")
async def send_quote_route(
    quote_id: int,
    data: QuoteSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.send")),
):
    result = send_quote_to_lead(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        quote_id=quote_id,
        channels=data.channels,
        subject=data.subject,
        message=data.message,
    )
    mark_quote_status(session, current_user.company_id, current_user.id, quote_id, "sent")
    return result

@router.post("/{quote_id}/accept")
async def accept_quote_route(
    quote_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    return mark_quote_status(session, current_user.company_id, current_user.id, quote_id, "accepted")


@router.post("/{quote_id}/reject")
async def reject_quote_route(
    quote_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    return mark_quote_status(session, current_user.company_id, current_user.id, quote_id, "rejected")