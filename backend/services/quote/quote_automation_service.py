"""
Quote automation — intent detection and auto-quote creation from inbound interactions.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from datetime import timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Lead, QuoteCreate, QuoteItemCreate, utc_now
from services.leads.engagement_service import record_quote_event
from services.leads.opt_out_service import is_lead_opted_out

logger = logging.getLogger(__name__)

QUOTE_TERMS = {"quote", "pricing", "price", "proposal", "estimate"}


def detect_quote_intent(text: str | None) -> bool:
    """Return True if text contains quote-request keywords."""
    if not text:
        return False
    text_lower = text.lower().strip()
    return any(term in text_lower for term in QUOTE_TERMS)


def should_trigger_quote_automation(
    session: Session,
    company_id: int,
    lead_id: int,
    intent: str,
    channel: str,
) -> bool:
    """
    Decide whether to fire quote automation.
    Only triggers on quote_requested intent, email/whatsapp channels,
    and when the lead has not opted out.
    """
    if intent != "quote_requested":
        return False
    if channel not in ("email", "whatsapp"):
        return False
    if is_lead_opted_out(session, company_id, lead_id, channel):
        return False
    return True


def auto_create_quote_from_interaction(
    session: Session,
    company_id: int,
    lead_id: int,
    interaction_id: int,
    request_text: str | None,
    channel: str,
) -> dict:
    """
    Automatically create a quote from an inbound interaction when product context
    is sufficient. Falls back to a follow-up CallTask when it is not.

    Returns:
        {
            "automation_triggered": bool,
            "quote_id": int | None,
            "call_task_id": int | None,
            "action": "auto_quote_sent" | "follow_up_task_created"
        }
    """
    from services.next_action_service import _resolve_quote_product_match
    from services.call.outbound_call_service import create_call_task
    from services.quote.quote_service import create_quote

    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    matched_product = _resolve_quote_product_match(session, company_id, lead, request_text)

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
                actor_user_id=0,
                data=quote_data,
            )
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
        except Exception as exc:
            logger.warning(
                "Auto-quote creation failed for lead=%d interaction=%d product=%s: %s — falling back to call task",
                lead_id, interaction_id, matched_product.name, exc,
            )

    task = create_call_task(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        actor_user_id=0,
        status="pending",
        notes=f"Review quote request from {channel}: {request_text[:200] if request_text else 'Product inquiry'}. Insufficient product context for auto-quote.",
    )
    return {
        "automation_triggered": True,
        "quote_id": None,
        "call_task_id": task.id,
        "action": "follow_up_task_created",
    }


def detect_and_process_quote_automation(
    session: Session,
    company_id: int,
    lead_id: int,
    interaction_id: int,
    text: str | None,
    channel: str,
) -> dict:
    """
    Detect quote intent and trigger automation in one call.

    Returns:
        {
            "intent_detected": bool,
            "automation_triggered": bool,
            "quote_id": int | None,
            "call_task_id": int | None,
            "action": str | None
        }
    """
    if not detect_quote_intent(text):
        return {
            "intent_detected": False,
            "automation_triggered": False,
            "quote_id": None,
            "call_task_id": None,
            "action": None,
        }

    if not should_trigger_quote_automation(session, company_id, lead_id, "quote_requested", channel):
        return {
            "intent_detected": True,
            "automation_triggered": False,
            "quote_id": None,
            "call_task_id": None,
            "action": None,
        }

    result = auto_create_quote_from_interaction(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        request_text=text,
        channel=channel,
    )
    return {"intent_detected": True, **result}
