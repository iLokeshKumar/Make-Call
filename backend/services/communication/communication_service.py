import logging
import os

from fastapi import HTTPException
from sqlmodel import Session, select

from credentials_service import get_company_credential, get_company_setting_value, get_email_credential
from email_service import get_styled_html, send_smtp_email
from models.models import Company, Interaction, Lead, Quote, utc_now
from services.communication.email_outbox_service import enqueue_email
from services.core.usage_service import check_and_increment
from services.core.feature_flag_service import require_feature
from services.analytics.email_tracking_service import (
    build_open_tracking_pixel,
    build_quote_view_url,
    build_unsubscribe_url,
    ensure_interaction_tracking_token,
    rewrite_click_tracking_links,
)
from services.leads.engagement_service import record_email_sent, record_quote_event, record_whatsapp_event
from services.leads.opt_out_service import is_lead_opted_out
from whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)


def _resolve_tracking_base(company: Company | None) -> str:
    # Priority:
    # TRACKING_BASE_URL — explicit override (use this in production)
    # FRONTEND_URL — frontend base (e.g. http://localhost:3006 in dev)
    # DOMAIN — ngrok/public backend URL
    # Backend localhost fallback
    # company.website is intentionally excluded — it is a branding field, not a routing endpoint
    return (
        os.getenv("TRACKING_BASE_URL")
        or os.getenv("FRONTEND_BASE_URL")
        or os.getenv("DOMAIN")
        or "http://localhost:6060"
    )


def send_email_to_lead(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    subject: str,
    body: str,
    cta_url: str = "",
    cta_label: str = "",
    attachment_paths: list[str] | None = None,
    parent_interaction_id: int | None = None,
) -> dict:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.email:
        raise HTTPException(status_code=400, detail="Lead has no email")
    if is_lead_opted_out(session, company_id, lead.id, "email"):
        raise HTTPException(status_code=400, detail="Lead has opted out of email")

    company = session.exec(select(Company).where(Company.id == company_id)).first()
    company_name = company.name if company else "Rio CRM"
    company_website = company.website if company and company.website else "https://rio-crm.example.com/"
    interaction = Interaction(
        company_id=company_id,
        lead_id=lead.id,
        user_id=actor_user_id,
        type="communication",
        channel="email",
        direction="outbound",
        source="system",
        content=subject,
        delivery_status="pending",
        metadata_json={"body": body},
        status="pending",
        started_at=utc_now(),
        ended_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
        parent_interaction_id=parent_interaction_id,
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    tracking_token = ensure_interaction_tracking_token(session, interaction)
    tracking_base = _resolve_tracking_base(company)
    
    # Track the CTA URL if provided and not already a tracking link
    tracked_cta_url = cta_url
    if cta_url and "/tracking/" not in cta_url:
        from services.analytics.email_tracking_service import build_email_click_tracking_url
        tracked_cta_url = build_email_click_tracking_url(tracking_base, tracking_token, cta_url)

    tracked_body = rewrite_click_tracking_links(body, tracking_base, tracking_token)
    unsubscribe_url = build_unsubscribe_url(tracking_base, tracking_token, "email")

    # Plain-text version: include unsubscribe link as text (no HTML available)
    plain_body = f"{tracked_body}\n\nTo unsubscribe: {unsubscribe_url}"

    # HTML version: unsubscribe goes in the styled footer, not the body
    html_body = get_styled_html(
        subject=subject,
        body=tracked_body,
        lead_name=lead.name,
        company_name=company_name,
        company_website=company_website,
        cta_url=tracked_cta_url,
        cta_label=cta_label,
        unsubscribe_url=unsubscribe_url,
    ) + build_open_tracking_pixel(tracking_base, tracking_token)

    check_and_increment(session, company_id, "emails_sent")

    # Queue via email outbox (async retry with exponential backoff) instead of calling SMTP directly. The outbox worker (email_outbox_loop) picks it up within EMAIL_OUTBOX_POLL_SECONDS (default 15 s) and handles retries.
    enqueue_email(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        to_email=lead.email,
        subject=subject,
        body=plain_body,
        html_body=html_body,
        company_name=company_name,
        attachment_paths=attachment_paths,
    )

    interaction.delivery_status = "queued"
    interaction.status = "pending"
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()

    record_email_sent(
        session=session,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_id=lead.id,
        interaction_id=interaction.id,
        tracking_payload={"tracking_token": tracking_token},
    )

    return {
        "success": True,
        "queued": True,
        "channel": "email",
        "lead_id": lead.id,
        "subject": subject,
        "interaction_id": interaction.id,
        "tracking_token": tracking_token,
        "attachment_count": len(attachment_paths or []),
    }


def _dispatch_whatsapp(
    session: Session,
    company_id: int,
    to_phone: str,
    body: str,
) -> dict:
    """
    Route a WhatsApp send to the configured telephony provider.
    Supports Twilio, Exotel, and falls back to Twilio for EnableX.
    """
    provider = (get_company_setting_value(session, company_id, "TELEPHONY_PROVIDER") or "twilio").lower()

    if provider == "exotel":
        # Exotel WhatsApp Business API
        import requests as _req
        account_sid = get_company_credential(session, company_id, "EXOTEL_ACCOUNT_SID")
        api_key     = get_company_credential(session, company_id, "EXOTEL_API_KEY")
        api_token   = get_company_credential(session, company_id, "EXOTEL_API_TOKEN")
        from_wa     = get_company_credential(session, company_id, "WHATSAPP_NUMBER") or get_company_credential(session, company_id, "WHATSAPP_NUMBER_FROM")
        if not all([account_sid, api_key, api_token, from_wa]):
            return {"success": False, "error": "Exotel WhatsApp credentials not configured"}
        try:
            url = f"https://api.exotel.com/v2/accounts/{account_sid}/whatsapp/send"
            resp = _req.post(
                url,
                auth=(api_key, api_token),
                json={"from": from_wa, "to": to_phone, "body": body},
                timeout=10,
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                return {"success": True, "message_sid": data.get("sid") or data.get("id"), "to_phone": to_phone, "from_phone": from_wa}
            return {"success": False, "error": f"Exotel returned {resp.status_code}: {resp.text[:200]}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    # Default: Twilio (also used as fallback for EnableX which has no native WA)
    return send_whatsapp_message(
        to_phone=to_phone,
        body=body,
        account_sid=get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID"),
        auth_token=get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN"),
        from_whatsapp_number=get_company_credential(session, company_id, "WHATSAPP_NUMBER") or get_company_credential(session, company_id, "WHATSAPP_NUMBER_FROM"),
    )


def send_whatsapp_to_lead(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    body: str,
    parent_interaction_id: int | None = None,
) -> dict:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    if not lead.normalized_phone:
        raise HTTPException(status_code=400, detail="Lead has no phone")
    if is_lead_opted_out(session, company_id, lead.id, "whatsapp"):
        raise HTTPException(status_code=400, detail="Lead has opted out of WhatsApp")

    require_feature(session, company_id, "whatsapp")
    check_and_increment(session, company_id, "whatsapp_sent")

    send_result = _dispatch_whatsapp(session, company_id, lead.normalized_phone, body)
    success = bool(send_result.get("success"))

    interaction = Interaction(
        company_id=company_id,
        lead_id=lead.id,
        user_id=actor_user_id,
        type="communication",
        channel="whatsapp",
        direction="outbound",
        source="system",
        content=body[:200],
        delivery_status="sent" if success else "failed",
        metadata_json={
            "body": body,
            "provider_message_sid": send_result.get("message_sid"),
            "to": send_result.get("to_phone"),
            "from": send_result.get("from_phone"),
        },
        status="completed" if success else "failed",
        started_at=utc_now(),
        ended_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
        parent_interaction_id=parent_interaction_id,
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    record_whatsapp_event(
        session=session,
        company_id=company_id,
        interaction_id=interaction.id,
        event_type="sent" if success else "failed",
        payload={
            "provider_message_sid": send_result.get("message_sid"),
            "to": send_result.get("to_phone"),
            "from": send_result.get("from_phone"),
        },
    )

    return {
        "success": success,
        "channel": "whatsapp",
        "lead_id": lead.id,
        "interaction_id": interaction.id,
        "provider_message_sid": send_result.get("message_sid"),
        "delivery_status": "sent" if success else "failed",
        "error": send_result.get("error"),
    }


def send_quote_to_lead(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
    channels: list[str],
    subject: str | None = None,
    message: str | None = None,
    attachment_paths: list[str] | None = None,
) -> dict:
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
        select(Lead).where(
            Lead.id == quote.lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    company = session.exec(select(Company).where(Company.id == company_id)).first()
    tracking_base = _resolve_tracking_base(company)
    quote_view_url = build_quote_view_url(tracking_base, quote.tracking_token) if quote.tracking_token else None
    email_subject = subject or f"Quotation {quote.quote_number}"
    email_message = message or f"Please find your quotation {quote.quote_number}. Total: {quote.currency} {quote.total_amount}"
    results = []

    if "email" in channels:
        results.append(
            send_email_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                subject=email_subject,
                body=email_message,
                cta_url=quote_view_url or "",
                cta_label="View Quote" if quote_view_url else "",
                attachment_paths=attachment_paths,
            )
        )
    if "whatsapp" in channels:
        results.append(
            send_whatsapp_to_lead(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead.id,
                body=email_message,
            )
        )

    if results:
        record_quote_event(
            session=session,
            company_id=company_id,
            quote_id=quote.id,
            event_type="sent",
            payload={"channels": channels},
        )

    return {"quote_id": quote.id, "quote_number": quote.quote_number, "results": results}
