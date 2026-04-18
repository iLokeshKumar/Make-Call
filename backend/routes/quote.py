import io
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from auth import PermissionChecker
from services.core.auth_service import user_has_any_permission
from database import get_session
from models.models import BulkQuotePdfRequest, Lead, Quote, QuoteCreate, User, QuoteSendRequest, utc_now
from services.quote.quote_service import (
    create_quote,
    get_quote_or_404,
    mark_quote_status,
)

from services.quote.quote_pdf_service import generate_quote_pdf
from services.communication.communication_service import send_quote_to_lead

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
    query = select(Quote).where(
        Quote.company_id == current_user.company_id,
        Quote.deleted_at.is_(None),
    )

    # Sales reps only see quotes for their own leads
    can_read_company = user_has_any_permission(session, current_user.id, {"lead.read_company"})
    if not can_read_company:
        user_lead_ids = select(Lead.id).where(
            Lead.company_id == current_user.company_id,
            Lead.owner_user_id == current_user.id,
            Lead.deleted_at.is_(None),
        )
        query = query.where(Quote.lead_id.in_(user_lead_ids))

    return session.exec(query.order_by(Quote.created_at.desc())).all()


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

@router.post("/bulk-pdf")
async def bulk_quote_pdf_route(
    data: BulkQuotePdfRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    """Generate PDFs for multiple quotes and return them as a ZIP archive."""
    buf = io.BytesIO()
    errors: list[dict] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for quote_id in data.quote_ids:
            try:
                quote = generate_quote_pdf(
                    session, current_user.company_id, current_user.id, quote_id
                )
                pdf_path = Path(quote.pdf_path)
                if pdf_path.exists():
                    zf.write(pdf_path, pdf_path.name)
            except Exception as exc:
                errors.append({"quote_id": quote_id, "error": str(exc)})
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=quotes.zip"},
    )


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


@router.delete("/{quote_id}")
async def delete_quote_route(
    quote_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("quote.manage")),
):
    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == current_user.company_id,
            Quote.deleted_at.is_(None),
        )
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    quote.deleted_at = utc_now()
    quote.updated_by = current_user.id
    session.add(quote)
    session.commit()
    return {"detail": "Quote deleted"}