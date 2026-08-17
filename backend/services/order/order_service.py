import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import (
    EventStore,
    Lead,
    Order,
    OrderCreate,
    OrderItem,
    Quote,
    QuoteItem,
    utc_now,
)

logger = logging.getLogger(__name__)

_VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending":    {"confirmed", "cancelled"},
    "confirmed":  {"processing", "cancelled"},
    "processing": {"shipped", "cancelled"},
    "shipped":    {"delivered", "cancelled"},
    "delivered":  {"closed", "cancelled"},
    "closed":     {"cancelled"},
    "cancelled":  set(),
}


def _emit_event(
    session: Session,
    company_id: int,
    aggregate_type: str,
    aggregate_id: int,
    event_type: str,
    payload: dict,
    actor_user_id: Optional[int] = None,
    correlation_id: Optional[str] = None,
) -> None:
    ev = EventStore(
        company_id=company_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id or str(uuid.uuid4()),
        payload=payload,
        actor_user_id=actor_user_id,
    )
    session.add(ev)


def _generate_order_number(session: Session, company_id: int) -> str:
    current_year = datetime.now(timezone.utc).year
    prefix = f"ORD-{current_year}-"
    orders = session.exec(
        select(Order).where(Order.company_id == company_id)
    ).all()
    max_seq = 0
    for order in orders:
        if order.order_number.startswith(prefix):
            try:
                seq = int(order.order_number[len(prefix):])
                max_seq = max(max_seq, seq)
            except ValueError:
                logger.debug("Skipping non-sequential order number: %s", order.order_number)
    return f"{prefix}{max_seq + 1:04d}"


def get_order_or_404(session: Session, company_id: int, order_id: int) -> Order:
    order = session.exec(
        select(Order).where(
            Order.id == order_id,
            Order.company_id == company_id,
        )
    ).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def list_orders(
    session: Session,
    company_id: int,
    status: Optional[str] = None,
    lead_id: Optional[int] = None,
) -> list[Order]:
    query = select(Order).where(Order.company_id == company_id)
    if status:
        query = query.where(Order.status == status)
    if lead_id:
        query = query.where(Order.lead_id == lead_id)
    return session.exec(query.order_by(Order.created_at.desc())).all()


def create_order_from_quote(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
) -> Order:
    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == company_id,
            Quote.deleted_at.is_(None),
        )
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    lead = session.exec(
        select(Lead).where(Lead.id == quote.lead_id, Lead.company_id == company_id)
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    order = Order(
        company_id=company_id,
        lead_id=quote.lead_id,
        account_id=quote.account_id,
        quote_id=quote.id,
        owner_user_id=actor_user_id,
        order_number=_generate_order_number(session, company_id),
        status="confirmed",
        currency=quote.currency,
        subtotal=quote.subtotal,
        discount_amount=quote.discount_amount,
        tax_amount=quote.tax_amount,
        total_amount=quote.total_amount,
        confirmed_at=utc_now(),
        notes=quote.notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    quote_items = session.exec(
        select(QuoteItem).where(
            QuoteItem.quote_id == quote.id,
            QuoteItem.company_id == company_id,
        )
    ).all()

    for qi in quote_items:
        item = OrderItem(
            order_id=order.id,
            company_id=company_id,
            product_id=qi.product_id,
            product_name_snapshot=qi.product_name_snapshot,
            sku_snapshot=qi.sku_snapshot,
            quantity=qi.quantity,
            unit_price=qi.unit_price,
            discount_percent=qi.discount_percent,
            line_total=qi.line_total,
            notes=qi.notes,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(item)

    session.commit()
    session.refresh(order)

    _emit_event(
        session=session,
        company_id=company_id,
        aggregate_type="order",
        aggregate_id=order.id,
        event_type="order.confirmed",
        payload={
            "order_number": order.order_number,
            "quote_id": quote_id,
            "total_amount": str(order.total_amount),
            "currency": order.currency,
        },
        actor_user_id=actor_user_id,
    )
    session.commit()
    return order


def create_order(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: OrderCreate,
) -> Order:
    lead = session.exec(
        select(Lead).where(Lead.id == data.lead_id, Lead.company_id == company_id)
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    order = Order(
        company_id=company_id,
        lead_id=data.lead_id,
        account_id=data.account_id,
        quote_id=data.quote_id,
        owner_user_id=actor_user_id,
        order_number=_generate_order_number(session, company_id),
        status="pending",
        currency=data.currency,
        subtotal=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        delivery_address=data.delivery_address,
        delivery_city=data.delivery_city,
        delivery_state=data.delivery_state,
        delivery_pincode=data.delivery_pincode,
        expected_delivery_at=data.expected_delivery_at,
        notes=data.notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(order)
    session.commit()
    session.refresh(order)

    _emit_event(
        session=session,
        company_id=company_id,
        aggregate_type="order",
        aggregate_id=order.id,
        event_type="order.pending",
        payload={
            "order_number": order.order_number,
            "lead_id": data.lead_id,
        },
        actor_user_id=actor_user_id,
    )
    session.commit()
    return order


def update_order_status(
    session: Session,
    company_id: int,
    actor_user_id: int,
    order_id: int,
    status: str,
    notes: Optional[str] = None,
) -> Order:
    order = get_order_or_404(session, company_id, order_id)

    allowed = _VALID_TRANSITIONS.get(order.status, set())
    if status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition order from '{order.status}' to '{status}'",
        )

    previous_status = order.status
    now = utc_now()
    order.status = status
    order.updated_at = now
    order.updated_by = actor_user_id
    if notes:
        order.notes = notes

    if status == "confirmed":
        order.confirmed_at = now
    elif status == "shipped":
        order.shipped_at = now
    elif status == "delivered":
        order.delivered_at = now
    elif status == "cancelled":
        order.cancelled_at = now

    session.add(order)
    session.commit()
    session.refresh(order)

    _emit_event(
        session=session,
        company_id=company_id,
        aggregate_type="order",
        aggregate_id=order.id,
        event_type=f"order.{status}",
        payload={
            "order_number": order.order_number,
            "previous_status": previous_status,
            "notes": notes,
        },
        actor_user_id=actor_user_id,
    )
    session.commit()
    return order


def cancel_order(
    session: Session,
    company_id: int,
    actor_user_id: int,
    order_id: int,
    reason: str,
) -> Order:
    order = get_order_or_404(session, company_id, order_id)

    if order.status == "cancelled":
        raise HTTPException(status_code=400, detail="Order is already cancelled")

    now = utc_now()
    order.status = "cancelled"
    order.cancelled_at = now
    order.cancellation_reason = reason
    order.updated_at = now
    order.updated_by = actor_user_id

    session.add(order)
    session.commit()
    session.refresh(order)

    _emit_event(
        session=session,
        company_id=company_id,
        aggregate_type="order",
        aggregate_id=order.id,
        event_type="order.cancelled",
        payload={
            "order_number": order.order_number,
            "reason": reason,
        },
        actor_user_id=actor_user_id,
    )
    session.commit()
    return order
