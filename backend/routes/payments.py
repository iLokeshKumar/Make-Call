from typing import Optional

from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import PaymentCreate, User
from services.order.payment_service import (
    get_payment_or_404,
    list_payments,
    record_payment,
    reconcile_invoice,
)

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post("")
async def record_payment_route(
    data: PaymentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("payment.manage")),
):
    return record_payment(session, current_user.company_id, current_user.id, data)


@router.get("")
async def list_payments_route(
    invoice_id: Optional[int] = None,
    lead_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("payment.read")),
):
    return list_payments(session, current_user.company_id, invoice_id=invoice_id, lead_id=lead_id)


@router.get("/{payment_id}")
async def get_payment_route(
    payment_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("payment.read")),
):
    return get_payment_or_404(session, current_user.company_id, payment_id)


@router.post("/reconcile/{invoice_id}")
async def reconcile_invoice_route(
    invoice_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("payment.manage")),
):
    return reconcile_invoice(session, current_user.company_id, invoice_id)
