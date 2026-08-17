from datetime import datetime, timedelta, timezone
from decimal import Decimal
from secrets import token_urlsafe
from typing import Any

import logging

from fastapi import HTTPException
from sqlmodel import Session, select

logger = logging.getLogger(__name__)

from models.models import EngagementEvent, Lead, Product, Quote, QuoteCreate, QuoteItem, QuoteItemCreate, utc_now
from services.leads.engagement_service import record_quote_event


def generate_quote_number(session: Session, company_id: int) -> str:
    current_year = datetime.now(timezone.utc).year
    prefix = f"Q-{company_id}-{current_year}-"

    quotes = session.exec(
        select(Quote).where(Quote.company_id == company_id)
    ).all()

    max_seq = 0
    for quote in quotes:
        if quote.quote_number.startswith(prefix):
            try:
                seq = int(quote.quote_number.replace(prefix, ""))
                max_seq = max(max_seq, seq)
            except ValueError:
                logger.debug("Skipping non-sequential quote number: %s", quote.quote_number)

    next_seq = max_seq + 1
    return f"{prefix}{next_seq:04d}"


def calculate_line_total(
    quantity: int,
    unit_price: Decimal,
    discount_percent: Decimal,
) -> Decimal:
    gross = Decimal(quantity) * unit_price
    discount_amount = (gross * discount_percent) / Decimal("100.00")
    return (gross - discount_amount).quantize(Decimal("0.01"))


def recalculate_quote_totals(session: Session, quote: Quote) -> Quote:
    items = session.exec(
        select(QuoteItem).where(
            QuoteItem.quote_id == quote.id,
            QuoteItem.company_id == quote.company_id,
        )
    ).all()

    subtotal = Decimal("0.00")
    gross_total = Decimal("0.00")

    for item in items:
        gross = Decimal(item.quantity) * item.unit_price
        gross_total += gross
        subtotal += item.line_total

    discount_amount = (gross_total - subtotal).quantize(Decimal("0.01"))
    tax_amount = Decimal("0.00")
    total_amount = (subtotal + tax_amount).quantize(Decimal("0.01"))

    quote.subtotal = subtotal
    quote.discount_amount = discount_amount
    quote.tax_amount = tax_amount
    quote.total_amount = total_amount
    quote.updated_at = utc_now()

    session.add(quote)
    session.commit()
    session.refresh(quote)
    return quote


def get_quote_or_404(session: Session, company_id: int, quote_id: int) -> Quote:
    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == company_id,
            Quote.deleted_at.is_(None),
        )
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    return quote


def create_quote(
    session: Session,
    company_id: int,
    actor_user_id: int,
    data: QuoteCreate,
) -> Quote:
    lead = session.exec(
        select(Lead).where(
            Lead.id == data.lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    quote = Quote(
        company_id=company_id,
        lead_id=data.lead_id,
        account_id=data.account_id,
        quote_number=generate_quote_number(session, company_id),
        status="draft",
        currency=data.currency,
        subtotal=Decimal("0.00"),
        discount_amount=Decimal("0.00"),
        tax_amount=Decimal("0.00"),
        total_amount=Decimal("0.00"),
        valid_until=data.valid_until or (utc_now() + timedelta(days=15)),
        tracking_token=token_urlsafe(24),
        notes=data.notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(quote)
    session.commit()
    session.refresh(quote)

    for item_data in data.items:
        add_quote_item(session, company_id, actor_user_id, quote.id, item_data, commit=False)

    session.commit()
    session.refresh(quote)

    record_quote_event(
        session=session,
        company_id=company_id,
        quote_id=quote.id,
        event_type="created",
        payload={
            "quote_number": quote.quote_number,
            "total_amount": str(quote.total_amount),
            "currency": quote.currency,
        },
    )

    return recalculate_quote_totals(session, quote)


def add_quote_item(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
    item_data: QuoteItemCreate,
    commit: bool = True,
) -> QuoteItem:
    quote = get_quote_or_404(session, company_id, quote_id)

    unit_price = item_data.unit_price
    product_name_snapshot = item_data.product_name_snapshot
    sku_snapshot = item_data.sku_snapshot

    if item_data.product_id:
        product = session.exec(
            select(Product).where(
                Product.id == item_data.product_id,
                Product.company_id == company_id,
            )
        ).first()
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        product_name_snapshot = product.name
        sku_snapshot = product.sku
        unit_price = product.price

    line_total = calculate_line_total(
        item_data.quantity,
        unit_price,
        item_data.discount_percent,
    )

    item = QuoteItem(
        quote_id=quote.id,
        company_id=company_id,
        product_id=item_data.product_id,
        product_name_snapshot=product_name_snapshot,
        sku_snapshot=sku_snapshot,
        quantity=item_data.quantity,
        unit_price=unit_price,
        discount_percent=item_data.discount_percent,
        line_total=line_total,
        notes=item_data.notes,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(item)

    if commit:
        session.commit()
        session.refresh(item)
        recalculate_quote_totals(session, quote)

    return item


_QUOTE_STATUS_ISM_STAGE: dict[str, str] = {
    "sent":        "quote_sent",
    "negotiation": "negotiation",
    "accepted":    "closed_won",
    "rejected":    "closed_lost",
}


def mark_quote_status(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
    status: str,
    payload: dict | None = None,
) -> Quote:
    quote = get_quote_or_404(session, company_id, quote_id)
    quote.status = status
    if status == "sent":
        quote.sent_at = utc_now()
    elif status == "accepted":
        quote.accepted_at = utc_now()
    elif status == "rejected":
        quote.rejected_at = utc_now()
    quote.updated_at = utc_now()
    quote.updated_by = actor_user_id
    session.add(quote)
    session.commit()
    session.refresh(quote)
    if status in {"accepted", "rejected"}:
        record_quote_event(
            session=session,
            company_id=company_id,
            quote_id=quote.id,
            event_type=status,
            payload=payload,
        )

    target_ism = _QUOTE_STATUS_ISM_STAGE.get(status)
    if target_ism and quote.lead_id:
        try:
            from services.call.outcome_service import advance_ism_stage
            lead = session.get(Lead, quote.lead_id)
            if lead and lead.company_id == company_id:
                if advance_ism_stage(lead, target_ism):
                    lead.updated_at = utc_now()
                    lead.updated_by = actor_user_id
                    session.add(lead)
                    session.commit()
        except Exception as ism_exc:
            logger.warning("[QuoteService] ISM stage update failed: %s", ism_exc)

    if status == "accepted" and quote.lead_id:
        try:
            from services.feedback.auto_csat_service import maybe_send_auto_csat
            maybe_send_auto_csat(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=quote.lead_id,
                interaction_id=None,
                trigger="quote",
            )
        except Exception as csat_exc:
            logger.warning("[AutoCSAT] Dispatch failed after quote accept: %s", csat_exc)

    return quote


def get_quote_by_tracking_token(session: Session, token: str) -> Quote | None:
    if not token:
        return None
    return session.exec(select(Quote).where(Quote.tracking_token == token)).first()


def record_quote_open_by_token(session: Session, token: str) -> dict[str, Any]:
    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote tracking token not found")
    return record_quote_event(
        session=session,
        company_id=quote.company_id,
        quote_id=quote.id,
        event_type="opened",
        payload={"tracking_token": token},
    )


def respond_to_quote_token(
    session: Session,
    token: str,
    response: str,
    actor_user_id: int | None = None,
) -> Quote:
    status_map = {"accept": "accepted", "reject": "rejected"}
    normalized = response.strip().lower()
    if normalized not in status_map:
        raise HTTPException(status_code=400, detail="Invalid response")

    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    target_status = status_map[normalized]
    if quote.status == target_status:
        return quote

    actor = actor_user_id or quote.created_by or 0
    mark_quote_status(
        session=session,
        company_id=quote.company_id,
        actor_user_id=actor,
        quote_id=quote.id,
        status=target_status,
        payload={"tracking_token": token},
    )
    session.refresh(quote)
    return quote


def get_public_quote_info(session: Session, token: str) -> dict[str, Any]:
    if not token:
        raise HTTPException(status_code=400, detail="Missing quote token")

    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    lead = session.get(Lead, quote.lead_id)
    events = session.exec(
        select(EngagementEvent)
        .where(EngagementEvent.quote_id == quote.id)
        .order_by(EngagementEvent.created_at.asc())
    ).all()

    timeline = []
    if quote.created_at:
        timeline.append({"label": "Quote created", "timestamp": quote.created_at.isoformat()})
    if quote.sent_at:
        timeline.append({"label": "Quote sent", "timestamp": quote.sent_at.isoformat()})
    if quote.opened_at:
        timeline.append({"label": "Quote opened", "timestamp": quote.opened_at.isoformat()})
    if quote.accepted_at:
        timeline.append({"label": "Quote accepted", "timestamp": quote.accepted_at.isoformat()})
    if quote.rejected_at:
        timeline.append({"label": "Quote rejected", "timestamp": quote.rejected_at.isoformat()})

    items = session.exec(
        select(QuoteItem).where(QuoteItem.quote_id == quote.id)
    ).all()

    return {
        "quote": {
            "id": quote.id,
            "quote_number": quote.quote_number,
            "status": quote.status,
            "currency": quote.currency,
            "total_amount": str(quote.total_amount),
            "valid_until": quote.valid_until.isoformat() if quote.valid_until else None,
            "tracking_token": quote.tracking_token,
            "notes": quote.notes,
            "lead_name": lead.name if lead else None,
            "lead_email": lead.email if lead else None,
            "lead_phone": lead.normalized_phone if lead else None,
        },
        "items": [
            {
                "id": it.id,
                "product_name": it.product_name_snapshot,
                "sku": it.sku_snapshot,
                "quantity": it.quantity,
                "unit_price": str(it.unit_price),
                "discount_percent": str(it.discount_percent),
                "line_total": str(it.line_total),
                "notes": it.notes,
            }
            for it in items
        ],
        "events": [
            {
                "event_type": event.event_type,
                "channel": event.channel,
                "payload": event.payload,
                "created_at": event.created_at.isoformat(),
            }
            for event in events
        ],
        "timeline": timeline,
    }


def negotiate_quote_by_token(session: Session, token: str, message: str, requested_discount: float | None = None) -> dict:
    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")
    if quote.status in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail=f"Quote already {quote.status}")

    now = utc_now()
    event = EngagementEvent(
        company_id=quote.company_id,
        lead_id=quote.lead_id,
        quote_id=quote.id,
        event_type="quote.negotiation",
        channel="quote",
        payload={
            "message": message,
            "requested_discount": requested_discount,
            "tracking_token": token,
        },
        created_at=now,
    )
    session.add(event)

    lead = session.get(Lead, quote.lead_id)
    if lead:
        lead.next_action = "negotiation"
        lead.next_action_due_at = now
        lead.updated_at = now
        session.add(lead)

    quote.status = "negotiation"
    quote.updated_at = now
    session.add(quote)
    session.commit()

    return {"status": "negotiation", "quote_id": quote.id}
