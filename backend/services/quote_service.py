from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from secrets import token_urlsafe

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Lead, Product, Quote, QuoteCreate, QuoteItem, QuoteItemCreate, utc_now
from services.tracking_service import record_quote_event


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
                pass

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

    # Track quote creation
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


def generate_quote_pdf(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
    output_dir: str = "quotes",
) -> Quote:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    quote = get_quote_or_404(session, company_id, quote_id)

    lead = session.exec(
        select(Lead).where(
            Lead.id == quote.lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    items = session.exec(
        select(QuoteItem).where(
            QuoteItem.quote_id == quote.id,
            QuoteItem.company_id == company_id,
        )
    ).all()

    if not items:
        raise HTTPException(status_code=400, detail="Quote has no items")

    Path(output_dir).mkdir(parents=True, exist_ok=True)
    file_path = Path(output_dir) / f"{quote.quote_number}.pdf"

    c = canvas.Canvas(str(file_path), pagesize=A4)
    width, height = A4
    y = height - 50

    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, y, f"Quotation {quote.quote_number}")
    y -= 30

    c.setFont("Helvetica", 11)
    c.drawString(40, y, f"Lead: {lead.name}")
    y -= 18
    c.drawString(40, y, f"Email: {lead.email or '-'}")
    y -= 18
    c.drawString(40, y, f"Phone: {lead.normalized_phone}")
    y -= 18
    c.drawString(40, y, f"Valid Until: {quote.valid_until.strftime('%Y-%m-%d') if quote.valid_until else '-'}")
    y -= 30

    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Product")
    c.drawString(260, y, "Qty")
    c.drawString(320, y, "Unit Price")
    c.drawString(430, y, "Line Total")
    y -= 20

    c.setFont("Helvetica", 10)
    for item in items:
        c.drawString(40, y, item.product_name_snapshot[:35])
        c.drawString(260, y, str(item.quantity))
        c.drawString(320, y, f"{quote.currency} {item.unit_price}")
        c.drawString(430, y, f"{quote.currency} {item.line_total}")
        y -= 18

        if y < 100:
            c.showPage()
            y = height - 50

    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(320, y, "Subtotal:")
    c.drawString(430, y, f"{quote.currency} {quote.subtotal}")
    y -= 18
    c.drawString(320, y, "Discount:")
    c.drawString(430, y, f"{quote.currency} {quote.discount_amount}")
    y -= 18
    c.drawString(320, y, "Tax:")
    c.drawString(430, y, f"{quote.currency} {quote.tax_amount}")
    y -= 18
    c.drawString(320, y, "Total:")
    c.drawString(430, y, f"{quote.currency} {quote.total_amount}")

    c.save()

    quote.pdf_path = str(file_path)
    quote.updated_at = utc_now()
    quote.updated_by = actor_user_id
    session.add(quote)
    session.commit()
    session.refresh(quote)
    record_quote_event(
        session=session,
        company_id=company_id,
        quote_id=quote.id,
        event_type="pdf_generated",
        payload={"pdf_path": quote.pdf_path},
    )

    return quote


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
    return quote


def get_quote_by_tracking_token(session: Session, token: str) -> Quote | None:
    if not token:
        return None
    return session.exec(select(Quote).where(Quote.tracking_token == token)).first()


def respond_to_quote_token(
    session: Session,
    token: str,
    response: str,
    actor_user_id: int | None = None,
) -> Quote:
    status_map = {
        "accept": "accepted",
        "reject": "rejected",
    }
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


def auto_create_quote_from_interaction(
    session: Session,
    company_id: int,
    lead_id: int,
    interaction_id: int,
    request_text: str | None,
    channel: str,
) -> dict[str, any]:
    """
    Automatically create a quote from an inbound interaction if product context is sufficient.
    If context is insufficient, create a CallTask for human review.
    
    Returns:
    {
        "automation_triggered": bool,
        "quote_id": int | None,
        "call_task_id": int | None,
        "action": "auto_quote_sent" | "follow_up_task_created"
    }
    """
    from services.next_action_service import _resolve_quote_product_match
    from services.outbound_call_service import create_call_task
    
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    # Try to resolve product match from interaction context
    matched_product = _resolve_quote_product_match(session, company_id, lead, request_text)
    
    # If we found a product match, auto-create and send quote
    if matched_product:
        try:
            quote_data = QuoteCreate(
                lead_id=lead_id,
                account_id=None,
                currency="INR",
                valid_until=utc_now() + timedelta(days=15),
                notes=f"Auto-generated quote from {channel} request: {request_text[:100] if request_text else 'Product inquiry'}",
                items=[
                    QuoteItemCreate(
                        product_id=matched_product.id,
                        product_name_snapshot=matched_product.name,
                        sku_snapshot=matched_product.sku,
                        quantity=1,
                        unit_price=matched_product.base_price or Decimal("0.00"),
                        discount_percent=Decimal("0.00"),
                    )
                ],
            )
            
            quote = create_quote(
                session=session,
                company_id=company_id,
                actor_user_id=0,  # System-created
                data=quote_data,
            )
            
            # Record automation event
            record_quote_event(
                session=session,
                company_id=company_id,
                quote_id=quote.id,
                event_type="auto_generated",
                payload={
                    "interaction_id": interaction_id,
                    "matched_product": matched_product.name,
                    "channel": channel,
                },
            )
            
            return {
                "automation_triggered": True,
                "quote_id": quote.id,
                "call_task_id": None,
                "action": "auto_quote_sent",
            }
        except Exception as e:
            # If quote creation fails, fall through to task creation
            pass
    
    # If no product match or quote creation failed, create a follow-up task
    task = create_call_task(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        actor_user_id=0,  # System-created
        status="pending",
        notes=f"Review quote request from {channel}: {request_text[:200] if request_text else 'Product inquiry'}. Insufficient product context for auto-quote.",
    )
    
    return {
        "automation_triggered": True,
        "quote_id": None,
        "call_task_id": task.id,
        "action": "follow_up_task_created",
    }
