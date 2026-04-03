import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlmodel import Session, select

from credentials_service import get_company_credential, get_company_setting_value
from database import get_session
from models.models import Interaction, Quote
from services.quote_service import respond_to_quote_token
from services.tracking_service import (
    get_public_quote_info,
    get_quote_by_tracking_token,
    ingest_whatsapp_webhook_event,
    ingest_email_webhook_event,
    record_email_click,
    record_email_open,
    record_quote_open_by_token,
    resolve_company_id_by_email_address,
    resolve_company_id_by_whatsapp_number,
    unsubscribe_lead,
)


TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs="
)


def _sorted_payload_pairs(payload: dict[str, Any]) -> str:
    return "".join(f"{key}{payload[key] or ''}" for key in sorted(payload.keys()))


def verify_twilio_signature(auth_token: str, signature: str, url: str, payload: dict[str, Any]) -> bool:
    if not signature:
        return True
    to_sign = url + _sorted_payload_pairs(payload)
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    return hmac.compare_digest(expected, signature)


def verify_email_signature(secret: str, payload: dict[str, Any], signature: str) -> bool:
    if not signature:
        return True
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hmac.new(secret.encode(), serialized.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

router = APIRouter(prefix="/tracking", tags=["Tracking"])


@router.get("/email/open/{token}")
async def email_open_tracking(
    token: str,
    session: Session = Depends(get_session),
):
    try:
        record_email_open(session, token)
    except Exception:
        pass
    return Response(content=TRANSPARENT_GIF, media_type="image/gif")


@router.get("/email/click/{token}")
async def email_click_tracking(
    token: str,
    target: str = Query(...),
    session: Session = Depends(get_session),
):
    try:
        record_email_click(session, token, target)
    except Exception:
        pass
    return RedirectResponse(url=target)


@router.get("/quote/open/{token}")
async def quote_open_tracking(
    token: str,
    session: Session = Depends(get_session),
):
    try:
        record_quote_open_by_token(session, token)
    except Exception:
        pass
    return Response(content=TRANSPARENT_GIF, media_type="image/gif")


@router.get("/quote/view/{token}")
async def quote_view_tracking(
    token: str,
    session: Session = Depends(get_session),
):
    try:
        record_quote_open_by_token(session, token)
    except Exception:
        pass

    quote = get_quote_by_tracking_token(session, token)
    if not quote:
        return {"status": "ignored", "reason": "token_not_found"}

    if quote.pdf_path and Path(quote.pdf_path).exists():
        return FileResponse(
            path=quote.pdf_path,
            media_type="application/pdf",
            filename=f"{quote.quote_number}.pdf",
        )
    return {
        "status": "tracked",
        "quote_id": quote.id,
        "quote_number": quote.quote_number,
        "reason": "pdf_not_available",
    }


@router.post("/unsubscribe")
async def unsubscribe_tracking(
    token: str = Query(...),
    channel: str = Query(...),
    reason: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    interaction = session.exec(select(Interaction).where(Interaction.channel == "email")).all()
    matched = None
    for item in interaction:
        metadata = item.metadata_json or {}
        if metadata.get("tracking_token") == token:
            matched = item
            break

    if matched is None:
        quote = session.exec(select(Quote).where(Quote.tracking_token == token)).first()
        if quote is not None:
            unsubscribe_lead(
                session=session,
                company_id=quote.company_id,
                actor_user_id=None,
                lead_id=quote.lead_id,
                channel=channel,
                reason=reason or "Unsubscribed via quote tracking link",
            )
            return {"status": "unsubscribed", "lead_id": quote.lead_id, "channel": channel}
        return {"status": "ignored", "reason": "token_not_found"}

    unsubscribe_lead(
        session=session,
        company_id=matched.company_id,
        actor_user_id=None,
        lead_id=matched.lead_id,
        channel=channel,
        reason=reason or "Unsubscribed via tracking link",
    )
    return {"status": "unsubscribed", "lead_id": matched.lead_id, "channel": channel}


@router.post("/whatsapp/status")
async def whatsapp_status_tracking(
    request: Request,
    session: Session = Depends(get_session),
):
    """Handle WhatsApp delivery status updates."""
    form = await request.form()
    payload = {key: value for key, value in form.items()}
    signature = request.headers.get("x-twilio-signature", "")
    company_id = resolve_company_id_by_whatsapp_number(session, payload.get("To"))
    if signature and company_id:
        auth_token = get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN")
        if auth_token and not verify_twilio_signature(auth_token, signature, str(request.url), payload):
            return JSONResponse(status_code=403, content={"status": "unauthorized", "reason": "invalid_signature"})
    
    # For status updates, we only need to record the status, not create interactions
    provider_message_sid = str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip() or None
    provider_status = str(payload.get("MessageStatus") or payload.get("SmsStatus") or "").strip().lower() or None
    
    if provider_message_sid and provider_status:
        interaction = _get_whatsapp_interaction_by_provider_sid(session, provider_message_sid)
        if interaction:
            metadata = dict(interaction.metadata_json or {})
            metadata.setdefault("provider_events", []).append(dict(payload))
            metadata["provider_message_sid"] = provider_message_sid
            if provider_status:
                metadata["provider_message_status"] = provider_status
            interaction.metadata_json = metadata
            interaction.updated_at = utc_now()

            delivery_status_map = {
                "queued": "pending",
                "accepted": "sent",
                "sent": "sent",
                "delivered": "delivered",
                "read": "read",
                "failed": "failed",
                "undelivered": "failed",
            }
            if provider_status in delivery_status_map:
                interaction.delivery_status = delivery_status_map[provider_status]
                if provider_status in {"failed", "undelivered"}:
                    interaction.status = "failed"
                elif provider_status in {"sent", "delivered", "read"}:
                    interaction.status = "completed"

            session.add(interaction)
            session.commit()
            record_whatsapp_event(
                session=session,
                company_id=interaction.company_id,
                interaction_id=interaction.id,
                event_type=f"status_{provider_status}",
                payload=dict(payload),
            )
            return {
                "status": "status_recorded",
                "interaction_id": interaction.id,
                "company_id": interaction.company_id,
                "provider_message_sid": provider_message_sid,
                "provider_status": provider_status,
            }
    
    return {"status": "ignored", "reason": "unsupported_status_payload"}


@router.post("/email/webhook")
async def email_tracking_webhook(
    request: Request,
    session: Session = Depends(get_session),
):
    payload: dict[str, str] = {}
    content_type = request.headers.get("content-type", "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        payload = {key: value for key, value in form.items()}
    normalized_to = (payload.get("To") or payload.get("Recipient") or "").strip().lower()
    company_id = resolve_company_id_by_email_address(session, normalized_to)
    signature = request.headers.get("x-email-signature", "")
    secret = get_company_setting_value(session, company_id, "INBOUND_EMAIL_WEBHOOK_SECRET") if company_id else None
    if secret and signature:
        if not verify_email_signature(secret, payload, signature):
            return JSONResponse(status_code=403, content={"status": "unauthorized", "reason": "invalid_signature"})
    return ingest_email_webhook_event(session, payload, forced_company_id=company_id)


@router.post("/quote/accept/{token}")
async def public_accept_quote(
    token: str,
    session: Session = Depends(get_session),
):
    quote = respond_to_quote_token(session, token, "accept")
    return {
        "status": "accepted",
        "quote_id": quote.id,
        "quote_number": quote.quote_number,
    }


@router.post("/quote/reject/{token}")
async def public_reject_quote(
    token: str,
    session: Session = Depends(get_session),
):
    quote = respond_to_quote_token(session, token, "reject")
    return {
        "status": "rejected",
        "quote_id": quote.id,
        "quote_number": quote.quote_number,
    }


@router.get("/quote/info/{token}")
async def public_quote_info(token: str, session: Session = Depends(get_session)):
    return get_public_quote_info(session, token)
