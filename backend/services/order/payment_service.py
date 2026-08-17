import logging
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    Invoice,
    Payment,
    PaymentCreate,
    utc_now,
)

logger = logging.getLogger(__name__)


def get_payment_or_404(session: Session, company_id: int, payment_id: int) -> Payment:
    payment = session.exec(
        select(Payment).where(
            Payment.id == payment_id,
            Payment.company_id == company_id,
        )
    ).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment


def list_payments(
    session: Session,
    company_id: int,
    invoice_id: Optional[int] = None,
    lead_id: Optional[int] = None,
) -> list[Payment]:
    query = select(Payment).where(Payment.company_id == company_id)
    if invoice_id:
        query = query.where(Payment.invoice_id == invoice_id)
    if lead_id:
        query = query.where(Payment.lead_id == lead_id)
    return session.exec(query.order_by(Payment.created_at.desc())).all()


def _update_invoice_payment_status(invoice: Invoice) -> None:
    if invoice.amount_due <= Decimal("0.00"):
        invoice.status = "paid"
        invoice.paid_at = utc_now()
    elif invoice.amount_paid > Decimal("0.00"):
        invoice.status = "partially_paid"
    invoice.updated_at = utc_now()


def record_payment(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: PaymentCreate,
) -> Payment:
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == data.invoice_id,
            Invoice.company_id == company_id,
        )
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.lead_id != data.lead_id:
        raise HTTPException(status_code=400, detail="Lead does not match invoice")

    now = utc_now()
    payment = Payment(
        company_id=company_id,
        invoice_id=data.invoice_id,
        lead_id=data.lead_id,
        amount=data.amount,
        currency=invoice.currency,
        status="captured",
        payment_method=data.payment_method,
        reference_number=data.reference_number,
        gateway=data.gateway,
        captured_at=now,
        notes=data.notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(payment)

    invoice.amount_paid = (invoice.amount_paid + data.amount).quantize(Decimal("0.01"))
    invoice.amount_due = (invoice.total_amount - invoice.amount_paid).quantize(Decimal("0.01"))
    invoice.updated_by = actor_user_id
    _update_invoice_payment_status(invoice)
    session.add(invoice)

    session.commit()
    session.refresh(payment)
    return payment


def reconcile_invoice(session: Session, company_id: int, invoice_id: int) -> Invoice:
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.company_id == company_id,
        )
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    payments = session.exec(
        select(Payment).where(
            Payment.invoice_id == invoice_id,
            Payment.company_id == company_id,
            Payment.status == "captured",
        )
    ).all()

    total_paid = sum((p.amount for p in payments), Decimal("0.00")).quantize(Decimal("0.01"))
    invoice.amount_paid = total_paid
    invoice.amount_due = (invoice.total_amount - total_paid).quantize(Decimal("0.01"))
    invoice.updated_at = utc_now()
    _update_invoice_payment_status(invoice)
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice
