import logging
import os

from fastapi import HTTPException
from sqlmodel import Session, select

from credentials_service import get_company_credential, get_company_setting_value
from email_service import get_styled_html, send_smtp_email
from models.models import Company, Interaction, Lead, Quote, utc_now
from services.tracking_service import (
    build_open_tracking_pixel,
    build_quote_view_url,
    build_unsubscribe_url,
    ensure_interaction_tracking_token,
    is_lead_opted_out,
    record_email_sent,
    record_whatsapp_event,
    record_quote_event,
    rewrite_click_tracking_links,
)
from whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)


def _resolve_tracking_base(company: Company | None) -> str:
    # Priority:
    # 1. TRACKING_BASE_URL — explicit override (use this in production)
    # 2. FRONTEND_URL — frontend base (e.g. http://localhost:3006 in dev)
    # 3. DOMAIN — ngrok/public backend URL
    # 4. Backend localhost fallback
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
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    tracking_token = ensure_interaction_tracking_token(session, interaction)
    tracking_base = _resolve_tracking_base(company)
    tracked_body = rewrite_click_tracking_links(body, tracking_base, tracking_token)
    unsubscribe_url = build_unsubscribe_url(tracking_base, tracking_token, "email")
    tracked_body = (
        f"{tracked_body}\n\nUnsubscribe from emails: {unsubscribe_url}"
        if tracked_body
        else f"Unsubscribe from emails: {unsubscribe_url}"
    )
    html_body = get_styled_html(
        subject=subject,
        body=tracked_body,
        lead_name=lead.name,
        company_name=company_name,
        company_website=company_website,
    ) + build_open_tracking_pixel(tracking_base, tracking_token)

    success = send_smtp_email(
        to_email=lead.email,
        subject=subject,
        body=tracked_body,
        html_body=html_body,
        company_name=company_name,
        smtp_host=get_company_credential(session, company_id, "SMTP_HOST"),
        smtp_port=get_company_credential(session, company_id, "SMTP_PORT"),
        smtp_username=get_company_credential(session, company_id, "SMTP_USERNAME"),
        smtp_password=get_company_credential(session, company_id, "SMTP_PASSWORD"),
        smtp_from_email=get_company_credential(session, company_id, "SMTP_FROM_EMAIL"),
    )

    interaction.delivery_status = "sent" if success else "failed"
    interaction.status = "completed" if success else "failed"
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()
    if success:
        record_email_sent(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead.id,
            interaction_id=interaction.id,
            tracking_payload={"tracking_token": tracking_token},
        )

    return {
        "success": success,
        "channel": "email",
        "lead_id": lead.id,
        "subject": subject,
        "interaction_id": interaction.id,
        "tracking_token": tracking_token,
    }


def send_whatsapp_to_lead(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    body: str,
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

    send_result = send_whatsapp_message(
        to_phone=lead.normalized_phone,
        body=body,
        account_sid=get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID"),
        auth_token=get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN"),
        from_whatsapp_number=get_company_credential(session, company_id, "WHATSAPP_NUMBER"),
    )
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
    }


def send_quote_to_lead(
    session: Session,
    company_id: int,
    actor_user_id: int,
    quote_id: int,
    channels: list[str],
    subject: str | None = None,
    message: str | None = None,
) -> dict:
    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == company_id,
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
    if quote_view_url:
        email_message = f"{email_message}\n\nView quote: {quote_view_url}"
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
