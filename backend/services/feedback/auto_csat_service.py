"""
Auto-CSAT Service
=================
Fires a CSAT email automatically after:
  - A call ends with a positive disposition (interested / callback_requested)
  - A quote is accepted

All failures are logged and swallowed - never block the caller.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session

from email_service import get_styled_html
from models.models import Company, Lead, User
from csat_service import get_csat_base_url, get_or_create_pending_csat
from communication.email_outbox_service import enqueue_email
from utils.encryption import decrypt_value

logger = logging.getLogger(__name__)

POSITIVE_OUTCOMES = {
    "answered_interested",
    "answered_callback_requested",
}

MISSED_CALL_OUTCOMES = {
    "no_answer",
    "voicemail",
}

DEFAULT_EXPIRY_HOURS = 72


def maybe_send_auto_csat(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: Optional[int],
    interaction_id: Optional[int] = None,
    trigger: str = "call",          # "call" | "quote" | "missed_call"
    normalized_outcome: str = "",   # only used for call trigger
) -> None:
    if not lead_id:
        return
    if trigger == "call" and normalized_outcome not in POSITIVE_OUTCOMES:
        return

    try:
        lead = session.get(Lead, lead_id)
        if not lead or lead.company_id != company_id:
            return
        if not lead.email:
            logger.info("[AutoCSAT] Skipping lead=%s no email", lead_id)
            return

        actor: Optional[User] = session.get(User, actor_user_id)
        company = session.get(Company, company_id)
        company_name = company.name if company else "Rio CRM"
        rep_name = (
            f"{actor.first_name or ''} {actor.last_name or ''}".strip()
            or (actor.email if actor else "our team")
        )

        fb, created = get_or_create_pending_csat(
            session,
            company_id=company_id,
            lead_id=lead_id,
            actor_user_id=actor_user_id,
            interaction_id=interaction_id,
            expires_hours=DEFAULT_EXPIRY_HOURS,
        )

        csat_url = f"{get_csat_base_url()}/feedback/{fb.token}"

        if trigger == "quote":
            subject = "You accepted our proposal — how did we do?"
            body = (
                f"Thank you for accepting the proposal from {rep_name} at {company_name}! "
                "We'd love to hear about your experience.\n\n"
                "It only takes 30 seconds — click below to share your feedback."
            )
        elif trigger == "missed_call":
            subject = f"We tried reaching you — {company_name}"
            body = (
                f"We tried calling you recently but couldn't connect. "
                f"We'd love to find the best way to help you.\n\n"
                "If you have a moment, we'd appreciate hearing from you — "
                "click below to share any feedback or questions."
            )
        else:
            subject = f"Quick feedback on your call with {rep_name}?"
            body = (
                f"Thank you for speaking with {rep_name} at {company_name}. "
                "We'd love to hear how the conversation went.\n\n"
                "It only takes 30 seconds — click below to share your feedback."
            )

        html = get_styled_html(
            subject=subject,
            body=body,
            lead_name=lead.name,
            company_name=company_name,
            cta_url=csat_url,
            cta_label="Share Feedback",
        )

        enqueue_email(
            session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            feedback_id=fb.id,
            to_email=decrypt_value(lead.email),
            subject=subject,
            body=body,
            html_body=html,
            company_name=company_name,
            dedupe_key=f"csat-feedback:{fb.id}",
        )

        logger.info(
            "[AutoCSAT] queued lead=%s trigger=%s fb_id=%s reused=%s",
            lead_id,
            trigger,
            fb.id,
            not created,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AutoCSAT] failed lead=%s trigger=%s: %s", lead_id, trigger, exc)
