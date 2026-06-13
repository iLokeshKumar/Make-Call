from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import InvoiceCreate, InvoiceSendRequest, User
from services.order.invoice_service import (
    check_auto_send_eligible,
    create_invoice,
    create_invoice_from_order,
    get_invoice_or_404,
    list_invoices,
    send_invoice,
)

router = APIRouter(prefix="/invoices", tags=["Invoices"])


@router.post("")
async def create_invoice_route(
    data: InvoiceCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("invoice.manage")),
):
    return create_invoice(session, current_user.company_id, current_user.id, data)


@router.post("/from-order/{order_id}")
async def create_invoice_from_order_route(
    order_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("invoice.manage")),
):
    return create_invoice_from_order(session, current_user.company_id, current_user.id, order_id)


@router.get("")
async def list_invoices_route(
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("invoice.read")),
):
    return list_invoices(session, current_user.company_id, status=status, lead_id=lead_id)


@router.get("/{invoice_id}")
async def get_invoice_route(
    invoice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("invoice.read")),
):
    return get_invoice_or_404(session, current_user.company_id, invoice_id)


@router.post("/{invoice_id}/send")
async def send_invoice_route(
    invoice_id: int,
    data: InvoiceSendRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("invoice.manage")),
):
    return send_invoice(
        session,
        current_user.company_id,
        current_user.id,
        invoice_id,
        send_via=data.send_via,
    )


@router.get("/{invoice_id}/auto-send-check")
async def auto_send_check_route(
    invoice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("invoice.read")),
):
    eligible, reasons = check_auto_send_eligible(session, current_user.company_id, invoice_id)
    return {"eligible": eligible, "reasons": reasons}
