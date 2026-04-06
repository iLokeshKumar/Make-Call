"""
Voice Quote Service
Auto-generates a PDF quote and dispatches it via all configured channels
when "send_quote" intent is detected post-call.

Flow:
  1. Extract required_products from transcript (already done by post_call_service)
  2. Fuzzy-match mentioned products against the company's product catalog
  3. Create a Quote with matched items (fallback: generic line item)
  4. Generate PDF (reportlab)
  5. Determine configured channels (email / whatsapp / both)
  6. Send via communication_service.send_quote_to_lead on all active channels
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models.models import Lead, Product, QuoteCreate, QuoteItemCreate, utc_now
from services.quote_service import create_quote, generate_quote_pdf
from services.communication_service import send_quote_to_lead
from credentials_service import get_company_credential

logger = logging.getLogger(__name__)


# Channel detection — send on every channel that has credentials configured

def _detect_channels(session: Session, company_id: int) -> list[str]:
    channels: list[str] = []

    # Email — needs at minimum SMTP_HOST + SMTP_USERNAME
    smtp_host = get_company_credential(session, company_id, "SMTP_HOST")
    smtp_user = get_company_credential(session, company_id, "SMTP_USERNAME")
    lead_placeholder = None  # we can't check lead email here, so channel is "available"
    if smtp_host and smtp_user:
        channels.append("email")

    # WhatsApp — Twilio path
    twilio_sid = get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID")
    wa_number = (
        get_company_credential(session, company_id, "WHATSAPP_NUMBER")
        or get_company_credential(session, company_id, "WHATSAPP_NUMBER_FROM")
    )
    if twilio_sid and wa_number:
        channels.append("whatsapp")

    # WhatsApp — Exotel path (only if Twilio not already added)
    if "whatsapp" not in channels:
        exotel_sid = get_company_credential(session, company_id, "EXOTEL_ACCOUNT_SID")
        exotel_wa = (
            get_company_credential(session, company_id, "WHATSAPP_NUMBER")
            or get_company_credential(session, company_id, "WHATSAPP_NUMBER_FROM")
        )
        if exotel_sid and exotel_wa:
            channels.append("whatsapp")

    # If nothing is configured, still attempt email so the result log is informative
    if not channels:
        channels = ["email"]

    return channels


# Product matching

def _match_products(
    session: Session,
    company_id: int,
    required_products_text: Optional[str],
) -> list[Product]:
    """Return a list of Product rows whose names appear in the transcript mention."""
    if not required_products_text:
        return []

    all_products = session.exec(
        select(Product).where(
            Product.company_id == company_id,
            Product.is_active == True,
        )
    ).all()

    mention_lower = required_products_text.lower()
    matched: list[Product] = []
    for p in all_products:
        if p.name.lower() in mention_lower or (p.sku and p.sku.lower() in mention_lower):
            matched.append(p)

    return matched


# Quote builder

def _build_quote_items(
    matched_products: list[Product],
    required_products_text: Optional[str],
) -> list[QuoteItemCreate]:
    if matched_products:
        return [
            QuoteItemCreate(
                product_id=p.id,
                product_name_snapshot=p.name,
                sku_snapshot=p.sku,
                quantity=1,
                unit_price=p.price,
                discount_percent=Decimal("0.00"),
            )
            for p in matched_products
        ]

    # No catalog match — add a single placeholder line item
    label = (required_products_text or "Requested Product")[:100]
    return [
        QuoteItemCreate(
            product_id=None,
            product_name_snapshot=label,
            sku_snapshot=None,
            quantity=1,
            unit_price=Decimal("0.00"),
            discount_percent=Decimal("0.00"),
            notes="Auto-generated from call — please update price before sharing",
        )
    ]


# Public entry point

async def auto_generate_and_send_quote(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    interaction_id: int,
    required_products_text: Optional[str] = None,
) -> dict:
    """
    Create a quote, generate its PDF, and send via all configured channels.
    Called from post_call_service when next_action == 'send_quote'.
    """
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        logger.warning("[VoiceQuote] Lead %s not found", lead_id)
        return {"success": False, "error": "lead_not_found"}

    # Match products
    matched = _match_products(session, company_id, required_products_text)
    logger.info(
        "[VoiceQuote] lead=%s matched_products=%s",
        lead_id, [p.name for p in matched],
    )

    # Create quote
    items = _build_quote_items(matched, required_products_text)
    quote_data = QuoteCreate(
        lead_id=lead_id,
        currency=matched[0].currency if matched else "INR",
        notes=f"Auto-generated from voice call (interaction #{interaction_id}). "
              f"Mentioned: {required_products_text or 'unspecified'}",
        items=items,
    )
    quote = create_quote(session, company_id, actor_user_id, quote_data)
    logger.info("[VoiceQuote] Created quote %s for lead %s", quote.quote_number, lead_id)

    # Generate PDF
    try:
        quote = generate_quote_pdf(session, company_id, actor_user_id, quote.id)
        logger.info("[VoiceQuote] PDF generated: %s", quote.pdf_path)
    except Exception as pdf_exc:
        logger.warning("[VoiceQuote] PDF generation failed: %s", pdf_exc)

    # Determine channels
    channels = _detect_channels(session, company_id)

    # Filter out email if lead has no email, filter out whatsapp if no phone
    if "email" in channels and not lead.email:
        channels.remove("email")
    if "whatsapp" in channels and not lead.normalized_phone:
        channels.remove("whatsapp")

    if not channels:
        logger.warning("[VoiceQuote] No valid channels available for lead %s", lead_id)
        return {
            "success": False,
            "quote_id": quote.id,
            "quote_number": quote.quote_number,
            "error": "no_channels_available",
        }

    # Send via all channels
    subject = f"Quotation {quote.quote_number} – as discussed"
    message = (
        f"Hi {lead.name},\n\n"
        f"As promised during our call, please find your quotation {quote.quote_number}.\n"
        f"Total: {quote.currency} {quote.total_amount}\n\n"
        f"This quote is valid until {quote.valid_until.strftime('%d %b %Y') if quote.valid_until else 'N/A'}.\n\n"
        f"Please feel free to reach out if you have any questions."
    )

    try:
        result = send_quote_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            quote_id=quote.id,
            channels=channels,
            subject=subject,
            message=message,
        )
        logger.info(
            "[VoiceQuote] Sent quote %s via channels=%s results=%s",
            quote.quote_number, channels, result,
        )
        return {
            "success": True,
            "quote_id": quote.id,
            "quote_number": quote.quote_number,
            "channels_used": channels,
            "send_result": result,
        }
    except Exception as send_exc:
        logger.error("[VoiceQuote] Send failed: %s", send_exc)
        return {
            "success": False,
            "quote_id": quote.id,
            "quote_number": quote.quote_number,
            "error": str(send_exc),
        }
