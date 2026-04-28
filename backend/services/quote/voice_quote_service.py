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
import re
from datetime import timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel import Session, select

from models.models import Lead, LeadRequirement, Product, QuoteCreate, QuoteItemCreate, utc_now
from services.quote.quote_service import create_quote
from services.quote.quote_pdf_service import generate_quote_pdf
from services.communication.communication_service import send_quote_to_lead
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


# Requirement-derived enrichment


def _latest_lead_requirement(session: Session, company_id: int, lead_id: int) -> Optional[LeadRequirement]:
    """Most recent LeadRequirement row for the lead — populated by post_call_service."""
    return session.exec(
        select(LeadRequirement)
        .where(
            LeadRequirement.company_id == company_id,
            LeadRequirement.lead_id == lead_id,
        )
        .order_by(LeadRequirement.id.desc())
        .limit(1)
    ).first()


def _parse_quantity_from_headcount(structured_data: Optional[dict]) -> int:
    """Pull headcount from the structured_data JSON if the post-call extractor
    wrote one (LLM tool args sometimes include it).  Defaults to 1.
    """
    if not structured_data:
        return 1
    raw = structured_data.get("headcount") or structured_data.get("employee_count") or structured_data.get("seats")
    if raw is None:
        return 1
    if isinstance(raw, (int, float)):
        return max(1, int(raw))
    s = str(raw)
    m = re.search(r"\d+", s)
    return max(1, int(m.group(0))) if m else 1


def _valid_until_from_timeline(timeline: Optional[str]):
    """Convert free-form timeline text ("this month", "in 2 weeks", "Q1")
    into a quote.valid_until date.  Falls back to 14 days.
    """
    now = utc_now()
    if not timeline:
        return now + timedelta(days=14)
    t = timeline.lower()
    if any(k in t for k in ("urgent", "asap", "today", "tomorrow", "this week")):
        return now + timedelta(days=7)
    if "month" in t or "q1" in t or "q2" in t or "30 days" in t:
        return now + timedelta(days=30)
    if "quarter" in t or "90 days" in t:
        return now + timedelta(days=60)
    m = re.search(r"(\d+)\s*(day|week|month)s?", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        days = n * {"day": 1, "week": 7, "month": 30}.get(unit, 1)
        return now + timedelta(days=max(7, min(days, 90)))
    return now + timedelta(days=14)


def _budget_tier_discount_pct(budget_range: Optional[str]) -> Decimal:
    """Map budget_range hints to a small auto-discount applied to all line
    items.  Conservative caps so the AI can never give away the store.

      - "tight", "limited", "low" → 5%
      - explicit ₹/$ amount that looks small (< 50k INR) → 5%
      - "premium", "no constraint", "enterprise" → 0%
      - default → 0%
    """
    if not budget_range:
        return Decimal("0.00")
    b = budget_range.lower()
    if any(k in b for k in ("tight", "limited", "low", "small", "budget-conscious")):
        return Decimal("5.00")
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(k|lakh|crore|cr|m)?", b)
    if m:
        try:
            num = float(m.group(1).replace(",", ""))
            unit = (m.group(2) or "").lower()
            multiplier = {"k": 1_000, "lakh": 100_000, "crore": 10_000_000, "cr": 10_000_000, "m": 1_000_000}.get(unit, 1)
            in_inr = num * multiplier
            if in_inr and in_inr < 50_000:
                return Decimal("5.00")
        except (ValueError, TypeError):
            pass
    return Decimal("0.00")


def _build_cover_note(
    interaction_id: int,
    requirement: Optional[LeadRequirement],
    required_products_text: Optional[str],
) -> str:
    """Compose the Quote.notes field from the call's captured context so the
    PDF cover section reflects what was actually discussed.  Lines are
    short — they end up in the quote PDF cover paragraph.
    """
    parts: list[str] = [f"Auto-generated from voice call (interaction #{interaction_id})."]
    if required_products_text:
        parts.append(f"Discussed: {required_products_text}.")
    if requirement:
        if requirement.use_case:
            parts.append(f"Use case: {requirement.use_case}.")
        if requirement.budget_range:
            parts.append(f"Budget: {requirement.budget_range}.")
        if requirement.timeline:
            parts.append(f"Timeline: {requirement.timeline}.")
        if requirement.decision_maker:
            parts.append(f"Decision-maker: {requirement.decision_maker}.")
        if requirement.pain_points:
            pains = requirement.pain_points.strip()
            if len(pains) > 200:
                pains = pains[:200] + "…"
            parts.append(f"Key pain points: {pains}.")
    return " ".join(parts)


# Quote builder
def _build_quote_items(
    matched_products: list[Product],
    required_products_text: Optional[str],
    quantity: int = 1,
    discount_pct: Decimal = Decimal("0.00"),
) -> list[QuoteItemCreate]:
    if matched_products:
        return [
            QuoteItemCreate(
                product_id=p.id,
                product_name_snapshot=p.name,
                sku_snapshot=p.sku,
                quantity=quantity,
                unit_price=p.price,
                discount_percent=discount_pct,
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
            quantity=quantity,
            unit_price=Decimal("0.00"),
            discount_percent=discount_pct,
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

    # Pull the LeadRequirement row written by post_call extractor — drives
    # quantity, discount, valid_until, and the cover-note bullets in the PDF.
    requirement = _latest_lead_requirement(session, company_id, lead_id)
    if requirement and not required_products_text and requirement.required_products:
        required_products_text = requirement.required_products

    quantity = _parse_quantity_from_headcount(requirement.structured_data if requirement else None)
    discount_pct = _budget_tier_discount_pct(requirement.budget_range if requirement else None)
    valid_until = _valid_until_from_timeline(requirement.timeline if requirement else None)

    # Match products
    matched = _match_products(session, company_id, required_products_text)
    logger.info(
        "[VoiceQuote] lead=%s matched_products=%s qty=%s discount=%s valid_until=%s",
        lead_id, [p.name for p in matched], quantity, discount_pct,
        valid_until.strftime("%Y-%m-%d") if valid_until else None,
    )

    # Create quote — cover note pulls from the LeadRequirement so the PDF
    # mirrors what was discussed on the call.
    items = _build_quote_items(matched, required_products_text, quantity=quantity, discount_pct=discount_pct)
    quote_data = QuoteCreate(
        lead_id=lead_id,
        currency=matched[0].currency if matched else "INR",
        notes=_build_cover_note(interaction_id, requirement, required_products_text),
        valid_until=valid_until,
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
