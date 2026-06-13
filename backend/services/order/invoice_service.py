import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    ConsentRecord,
    Invoice,
    InvoiceCreate,
    InvoiceItem,
    Lead,
    Order,
    OrderItem,
    utc_now,
)

logger = logging.getLogger(__name__)


def _generate_invoice_number(session: Session, company_id: int) -> str:
    current_year = datetime.now(timezone.utc).year
    prefix = f"INV-{current_year}-"
    invoices = session.exec(
        select(Invoice).where(Invoice.company_id == company_id)
    ).all()
    max_seq = 0
    for invoice in invoices:
        if invoice.invoice_number.startswith(prefix):
            try:
                seq = int(invoice.invoice_number[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                logger.debug("Skipping non-sequential invoice number: %s", invoice.invoice_number)
    return f"{prefix}{max_seq + 1:04d}"


def get_invoice_or_404(session: Session, company_id: int, invoice_id: int) -> Invoice:
    invoice = session.exec(
        select(Invoice).where(
            Invoice.id == invoice_id,
            Invoice.company_id == company_id,
        )
    ).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return invoice


def list_invoices(
    session: Session,
    company_id: int,
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
) -> list[Invoice]:
    query = select(Invoice).where(Invoice.company_id == company_id)
    if status:
        query = query.where(Invoice.status == status)
    if lead_id:
        query = query.where(Invoice.lead_id == lead_id)
    return session.exec(query.order_by(Invoice.created_at.desc())).all()


def create_invoice_from_order(
    session: Session,
    company_id: int,
    actor_user_id: int,
    order_id: int,
) -> Invoice:
    order = session.exec(
        select(Order).where(
            Order.id == order_id,
            Order.company_id == company_id,
        )
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    invoice = Invoice(
        company_id=company_id,
        order_id=order.id,
        lead_id=order.lead_id,
        account_id=order.account_id,
        owner_user_id=actor_user_id,
        invoice_number=_generate_invoice_number(session, company_id),
        status="draft",
        currency=order.currency,
        subtotal=order.subtotal,
        discount_amount=order.discount_amount,
        tax_amount=order.tax_amount,
        total_amount=order.total_amount,
        amount_paid=Decimal("0.00"),
        amount_due=order.total_amount,
        notes=order.notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)

    order_items = session.exec(
        select(OrderItem).where(
            OrderItem.order_id == order.id,
            OrderItem.company_id == company_id,
        )
    ).all()

    for oi in order_items:
        inv_item = InvoiceItem(
            invoice_id=invoice.id,
            company_id=company_id,
            order_item_id=oi.id,
            description=oi.product_name_snapshot,
            quantity=oi.quantity,
            unit_price=oi.unit_price,
            tax_rate=Decimal("0.00"),
            line_total=oi.line_total,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(inv_item)

    session.commit()
    session.refresh(invoice)
    return invoice


def create_invoice(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: InvoiceCreate,
) -> Invoice:
    lead = session.exec(
        select(Lead).where(Lead.id == data.lead_id, Lead.company_id == company_id)
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    invoice = Invoice(
        company_id=company_id,
        order_id=data.order_id,
        lead_id=data.lead_id,
        account_id=data.account_id,
        owner_user_id=actor_user_id,
        invoice_number=_generate_invoice_number(session, company_id),
        status="draft",
        currency=data.currency,
        subtotal=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        amount_paid=Decimal("0.00"),
        amount_due=Decimal("0.00"),
        due_date=data.due_date,
        gst_number=data.gst_number,
        billing_address=data.billing_address,
        notes=data.notes,
        requires_approval=data.requires_approval,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(invoice)
    session.commit()
    session.refresh(invoice)
    return invoice


def send_invoice(
    session: Session,
    company_id: int,
    actor_user_id: int,
    invoice_id: int,
    send_via: list[str],
) -> Invoice:
    invoice = get_invoice_or_404(session, company_id, invoice_id)

    if invoice.status not in ("draft", "overdue"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot send invoice with status '{invoice.status}'",
        )

    now = utc_now()
    invoice.status = "sent"
    invoice.sent_at = now
    invoice.updated_at = now
    invoice.updated_by = actor_user_id

    session.add(invoice)
    session.commit()
    session.refresh(invoice)

    logger.info(
        "[InvoiceService] Invoice %s sent via channels: %s",
        invoice.invoice_number,
        send_via,
    )
    return invoice


def mark_overdue(session: Session, company_id: int) -> int:
    now = utc_now()
    invoices = session.exec(
        select(Invoice).where(
            Invoice.company_id == company_id,
            Invoice.status == "sent",
            Invoice.due_date.isnot(None),
            Invoice.due_date < now,
        )
    ).all()

    count = 0
    for invoice in invoices:
        invoice.status = "overdue"
        invoice.overdue_at = now
        invoice.updated_at = now
        session.add(invoice)
        count += 1

    if count:
        session.commit()
    return count


def check_auto_send_eligible(
    session: Session,
    company_id: int,
    invoice_id: int,
) -> tuple[bool, list[str]]:
    invoice = get_invoice_or_404(session, company_id, invoice_id)
    reasons: list[str] = []

    if invoice.requires_approval:
        reasons.append("Invoice requires manual approval before sending")

    lead = session.exec(
        select(Lead).where(Lead.id == invoice.lead_id, Lead.company_id == company_id)
    ).first()

    if lead:
        if lead.status in ("dispute", "churned"):
            reasons.append(f"Lead has dispute/churn status: {lead.status}")

        consents = session.exec(
            select(ConsentRecord).where(
                ConsentRecord.company_id == company_id,
                ConsentRecord.lead_id == lead.id,
            )
        ).all()

        granted_channels = {c.channel for c in consents if c.status == "granted"}
        required_channels = {"email"}
        missing = required_channels - granted_channels
        if missing:
            reasons.append(f"Missing consent for channels: {', '.join(sorted(missing))}")
    else:
        reasons.append("Lead not found")

    eligible = len(reasons) == 0
    return eligible, reasons
