from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from email_service import get_styled_html
from models.models import Company, Feedback, Lead, User
from services.feedback.csat_service import get_csat_base_url, get_or_create_pending_csat
from services.communication.email_outbox_service import enqueue_email
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

# Outcomes where the customer was actually engaged enough to give feedback. Broader than POSITIVE_OUTCOMES — includes neutral and negative dispositions because qualitative feedback from an unhappy caller is more valuable than silence.  Excludes no_answer / voicemail (no conversation happened).
ENGAGED_OUTCOMES = {
    "answered_interested",
    "answered_callback_requested",
    "answered_not_interested",
    "answered_neutral",
    "answered_objection",
    "answered_general",
    "answered",
}


def _has_verbal_feedback(session: Session, company_id: int, interaction_id: Optional[int]) -> bool:
    """True iff the customer already gave a verbal rating/comment on this call.

    Skip the post-call CSAT nudge in that case — we already have their voice
    captured by the post_call extractor (see post_call_service.py).
    """
    if not interaction_id:
        return False
    fb = session.exec(
        select(Feedback).where(
            Feedback.company_id == company_id,
            Feedback.interaction_id == interaction_id,
            Feedback.source == "customer",
            Feedback.feedback_type == "csat",
            Feedback.status == "submitted",
        ).limit(1)
    ).first()
    return fb is not None


def maybe_send_auto_csat(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: Optional[int],
    interaction_id: Optional[int] = None,
    trigger: str = "call",          # "call" | "quote" | "missed_call"
    normalized_outcome: str = "",   # only used for call trigger
    channel: str = "auto",          # "auto" | "email" | "whatsapp" | "both"
) -> None:
    """Queue a CSAT feedback request via email and/or WhatsApp.

    For trigger="call":
      - Skips entirely if the customer already gave verbal feedback on the call.
      - Triggers for any ENGAGED_OUTCOMES (broader than POSITIVE_OUTCOMES).

    Channel resolution when channel="auto":
      - WhatsApp first (better CTR in India, instant), email as fallback.
      - Falls back to whichever channel actually has a contact value.
    """
    if not lead_id:
        logger.info("[AutoCSAT] skip: no lead_id (trigger=%s)", trigger)
        return

    if trigger == "call":
        if normalized_outcome and normalized_outcome not in ENGAGED_OUTCOMES:
            logger.info(
                "[AutoCSAT] skip lead=%s: outcome=%s not in ENGAGED_OUTCOMES",
                lead_id, normalized_outcome,
            )
            return
        if _has_verbal_feedback(session, company_id, interaction_id):
            logger.info("[AutoCSAT] skip lead=%s: verbal feedback already captured", lead_id)
            return

    logger.info(
        "[AutoCSAT] dispatch lead=%s trigger=%s outcome=%s channel=%s",
        lead_id, trigger, normalized_outcome, channel,
    )

    try:
        lead = session.get(Lead, lead_id)
        if not lead or lead.company_id != company_id:
            return
        if lead.deleted_at is not None:
            logger.info("[AutoCSAT] skip lead=%s: lead is soft-deleted", lead_id)
            return

        has_email = bool(lead.email)
        has_phone = bool(getattr(lead, "normalized_phone", None) or getattr(lead, "phone", None))
        if not has_email and not has_phone:
            logger.info("[AutoCSAT] Skipping lead=%s — no email or phone", lead_id)
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

        # Channel resolution
        send_email = channel in ("email", "both") or (channel == "auto" and not has_phone)
        send_wa = channel in ("whatsapp", "both") or (channel == "auto" and has_phone)

        sent_channels: list[str] = []

        if send_email and has_email:
            html = get_styled_html(
                subject=subject,
                body=body,
                lead_name=lead.name,
                company_name=company_name,
                cta_url=csat_url,
                cta_label="Share Feedback",
            )
            try:
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
                sent_channels.append("email")
            except Exception as ex:
                logger.warning("[AutoCSAT] email queue failed lead=%s: %s", lead_id, ex)

        if send_wa and has_phone:
            try:
                wa_body = (
                    f"Hi {lead.name or 'there'}, thanks for chatting with {rep_name} at {company_name}! "
                    f"How was the call? Tap to share quick feedback (30s): {csat_url}"
                )
                from services.communication.communication_service import send_whatsapp_to_lead
                send_whatsapp_to_lead(
                    session=session,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                    lead_id=lead_id,
                    body=wa_body,
                )
                sent_channels.append("whatsapp")
            except Exception as ex:
                logger.warning("[AutoCSAT] whatsapp send failed lead=%s: %s", lead_id, ex)

                if "email" not in sent_channels and has_email and channel == "auto":
                    try:
                        html = get_styled_html(
                            subject=subject, body=body, lead_name=lead.name,
                            company_name=company_name, cta_url=csat_url, cta_label="Share Feedback",
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
                        sent_channels.append("email-fallback")
                    except Exception as ex2:
                        logger.warning("[AutoCSAT] email fallback also failed lead=%s: %s", lead_id, ex2)

        logger.info(
            "[AutoCSAT] queued lead=%s trigger=%s fb_id=%s reused=%s channels=%s",
            lead_id, trigger, fb.id, not created, sent_channels,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[AutoCSAT] failed lead=%s trigger=%s: %s", lead_id, trigger, exc)
