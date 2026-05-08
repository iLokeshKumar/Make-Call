import base64
import hashlib
import hmac
import json
import logging
import os
import time
from collections import defaultdict, deque
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from sqlmodel import Session, select

from credentials_service import get_company_credential, get_company_setting_value
from database import get_session
from models.models import Interaction, Quote, utc_now
from services.leads.engagement_service import record_email_click, record_email_open
from services.communication.inbound_email_service import ingest_email_webhook_event, resolve_company_id_by_email_address
from services.communication.inbound_whatsapp_service import ingest_whatsapp_webhook_event, resolve_company_id_by_whatsapp_number
from services.leads.opt_out_service import unsubscribe_lead
from services.quote.quote_service import (
    get_public_quote_info,
    get_quote_by_tracking_token,
    negotiate_quote_by_token,
    record_quote_open_by_token,
    respond_to_quote_token,
)

logger = logging.getLogger(__name__)

# Rate limiting — sliding window, in-memory, per client IP

_RL_LOCK = Lock()
_RL_BUCKETS: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """Best-effort real IP extraction (honours X-Forwarded-For behind proxies)."""
    forwarded_for = request.headers.get("x-forwarded-for")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


def _is_rate_limited(*, key: str, limit: int, window_seconds: int) -> bool:
    """
    Sliding-window counter.  Returns True when the caller is over budget.
    Thread-safe via a single global Lock (in-process only — sufficient for
    single-worker deployments; swap for Redis if you run multiple workers).
    """
    now = time.monotonic()
    with _RL_LOCK:
        dq = _RL_BUCKETS[key]
        cutoff = now - window_seconds
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= limit:
            return True
        dq.append(now)
        return False


def _rate_limit_response() -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Too many requests — please slow down."},
        headers={"Retry-After": "60"},
    )


TRANSPARENT_GIF = base64.b64decode(
    "R0lGODlhAQABAIABAP///wAAACwAAAAAAQABAAACAkQBADs="
)

# Signature verification

# Set WEBHOOK_SIGNATURE_STRICT=true in production to reject unsigned requests.
_STRICT_MODE: bool = os.getenv("WEBHOOK_SIGNATURE_STRICT", "true").lower() == "true"


def _sorted_payload_pairs(payload: dict[str, Any]) -> str:
    return "".join(f"{key}{payload[key] or ''}" for key in sorted(payload.keys()))


def _canonical_url(request: Request) -> str:
    """
    Build the canonical URL that Twilio used when it signed the request.
    In production behind a reverse-proxy, forward headers may supply the
    real scheme/host.  We honour X-Forwarded-Proto and X-Forwarded-Host
    so the computed signature always matches what Twilio signed against.
    """
    scheme = (
        request.headers.get("x-forwarded-proto")
        or request.url.scheme
    )
    host = (
        request.headers.get("x-forwarded-host")
        or request.headers.get("host")
        or request.url.netloc
    )
    # Twilio signs the full URL *including* query string.
    path_qs = request.url.path
    if request.url.query:
        path_qs += "?" + request.url.query
    return f"{scheme}://{host}{path_qs}"


def verify_twilio_signature(
    auth_token: str,
    signature: str,
    url: str,
    payload: dict[str, Any],
) -> bool:
    """
    Validate a Twilio X-Twilio-Signature header.

    Twilio's algorithm:
      1. Concatenate the full URL with sorted form-field key+value pairs.
      2. HMAC-SHA1 using the auth token as the key.
      3. Base64-encode and compare.

    In strict mode (WEBHOOK_SIGNATURE_STRICT=true) an *empty* signature
    string is treated as invalid so unsigned traffic is rejected.
    """
    if not signature:
        if _STRICT_MODE:
            logger.warning("Twilio signature missing (strict mode) url=%s", url)
            return False
        return True

    to_sign = url + _sorted_payload_pairs(payload)
    expected = base64.b64encode(
        hmac.new(auth_token.encode(), to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    valid = hmac.compare_digest(expected, signature)
    if not valid:
        logger.warning(
            "Twilio signature mismatch: expected=%s got=%s url=%s",
            expected[:12] + "...",
            signature[:12] + "...",
            url,
        )
    return valid


def verify_email_signature(
    secret: str,
    payload: dict[str, Any],
    signature: str,
) -> bool:
    """
    Validate an inbound email webhook HMAC-SHA256 signature.
    Same strict-mode logic as the Twilio helper above.
    """
    if not signature:
        if _STRICT_MODE:
            logger.warning("Email webhook signature missing (strict mode)")
            return False
        return True

    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hmac.new(secret.encode(), serialized.encode("utf-8"), hashlib.sha256).hexdigest()
    valid = hmac.compare_digest(expected, signature)
    if not valid:
        logger.warning("Email webhook signature mismatch")
    return valid


def _whatsapp_webhook_guard(
    request: Request,
    session: Session,
    payload: dict[str, Any],
) -> JSONResponse | None:
    """
    Shared Twilio/WhatsApp signature guard.  Returns a 403 JSONResponse if the
    signature fails, otherwise returns None (request is allowed through).
    """
    signature = request.headers.get("x-twilio-signature", "")
    company_id = resolve_company_id_by_whatsapp_number(session, payload.get("To"))

    if not company_id:
        # Can't look up auth token without knowing the company. In strict mode we reject; in dev mode we let it through.
        if _STRICT_MODE and not signature:
            return JSONResponse(
                status_code=403,
                content={"status": "unauthorized", "reason": "unknown_recipient_strict_mode"},
            )
        return None

    auth_token = get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN")
    if not auth_token:
        logger.warning("No TWILIO_AUTH_TOKEN for company_id=%d – skipping signature check", company_id)
        return None

    canonical = _canonical_url(request)
    if not verify_twilio_signature(auth_token, signature, canonical, payload):
        return JSONResponse(
            status_code=403,
            content={"status": "unauthorized", "reason": "invalid_signature"},
        )
    return None


router = APIRouter(prefix="/tracking", tags=["Tracking"])


@router.get("/email/open/{token}")
async def email_open_tracking(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"email_open:{ip}", limit=20, window_seconds=60):
        # Still return the pixel so the email client doesn't show a broken image, but silently drop the recording.
        return Response(content=TRANSPARENT_GIF, media_type="image/gif")
    try:
        record_email_open(session, token)
    except Exception:
        pass
    return Response(content=TRANSPARENT_GIF, media_type="image/gif")


@router.get("/email/click/{token}")
async def email_click_tracking(
    token: str,
    request: Request,
    target: str = Query(...),
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    full_url = str(request.url)
    logger.info("[Tracking] Email click: token=%s, target=%s, ip=%s, full_url=%s", token, target, ip, full_url)

    if _is_rate_limited(key=f"email_click:{ip}", limit=30, window_seconds=60):
        return _rate_limit_response()
    try:
        record_email_click(session, token, target)
    except Exception:
        pass
    return RedirectResponse(url=target)


@router.get("/quote/open/{token}")
async def quote_open_tracking(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"quote_open:{ip}", limit=20, window_seconds=60):
        return Response(content=TRANSPARENT_GIF, media_type="image/gif")
    try:
        record_quote_open_by_token(session, token)
    except Exception:
        pass
    return Response(content=TRANSPARENT_GIF, media_type="image/gif")


@router.get("/quote/view/{token}")
async def quote_view_tracking(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"quote_view:{ip}", limit=30, window_seconds=60):
        return _rate_limit_response()
    try:
        record_quote_open_by_token(session, token)
    except Exception:
        pass

    frontend_base = (
        os.getenv("FRONTEND_BASE_URL")
        or os.getenv("TRACKING_BASE_URL")
        or "http://localhost:3006"
    )
    return RedirectResponse(url=f"{frontend_base}/q/{token}", status_code=302)


@router.post("/unsubscribe")
async def unsubscribe_tracking(
    request: Request,
    token: str = Query(...),
    channel: str = Query(...),
    reason: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"unsub:{ip}", limit=5, window_seconds=60):
        return _rate_limit_response()
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


@router.post("/whatsapp/inbound")
async def whatsapp_inbound_webhook(
    request: Request,
    session: Session = Depends(get_session),
):
    """Receive inbound WhatsApp messages from Twilio (async via AgentTask)."""
    form = await request.form()
    payload = {key: value for key, value in form.items()}

    guard_response = _whatsapp_webhook_guard(request, session, payload)
    if guard_response is not None:
        return guard_response
    
    return ingest_whatsapp_webhook_event(session, payload)

    # from services.agent.agent_task_service import create_agent_task
    # from services.communication.inbound_whatsapp_service import resolve_company_id_by_whatsapp_number
    
    # # Resolve company_id synchronously to route the task to the right tenant
    # to_number = payload.get("To", "")
    # company_id = resolve_company_id_by_whatsapp_number(session, to_number)
    
    # if not company_id:
    #     logger.warning("[Tracking] Could not resolve company for WhatsApp message to %s", to_number)
    #     return {"status": "ignored", "reason": "company_not_found"}

    # create_agent_task(
    #     session=session,
    #     company_id=company_id,
    #     task_type="process_inbound_whatsapp",
    #     assigned_agent="webhook_handlers",
    #     input_json={"payload": payload},
    #     idempotency_key=f"wa_inbound:{payload.get('MessageSid')}",
    #     requires_approval=False,
    # )
    # return {"status": "queued"}


@router.post("/whatsapp/status")
async def whatsapp_status_tracking(
    request: Request,
    session: Session = Depends(get_session),
):
    """Handle WhatsApp delivery status updates from Twilio (async via AgentTask)."""
    form = await request.form()
    payload = {key: value for key, value in form.items()}

    guard_response = _whatsapp_webhook_guard(request, session, payload)
    if guard_response is not None:
        return guard_response
    
    provider_message_sid = str(payload.get("MessageSid") or payload.get("SmsSid") or "").strip() or None
    provider_status = str(payload.get("MessageStatus") or payload.get("SmsStatus") or "").strip().lower() or None

    # from services.agent.agent_task_service import create_agent_task
    # from services.communication.inbound_whatsapp_service import resolve_company_id_by_whatsapp_number
    
    # company_id = resolve_company_id_by_whatsapp_number(session, payload.get("To"))
    # if not company_id:
    #     return {"status": "ignored", "reason": "company_not_found"}

    if provider_message_sid and provider_status:
        from models.models import Interaction
        interaction = session.exec(
                select(Interaction).where(
                    Interaction.metadata_json["provider_message_sid"].as_string() == provider_message_sid
                )
            ).first()

    # create_agent_task(
    #     session=session,
    #     company_id=company_id,
    #     task_type="process_whatsapp_status",
    #     assigned_agent="webhook_handlers",
    #     input_json={"payload": payload},
    #     idempotency_key=f"wa_status:{payload.get('MessageSid')}:{payload.get('MessageStatus')}",
    #     requires_approval=False,
    # )
    # return {"status": "queued"}

    if interaction:
                metadata = dict(interaction.metadata_json or {})
                metadata.setdefault("provider_events", []).append(dict(payload))
                metadata["provider_message_sid"] = provider_message_sid
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
    """Handle inbound email webhooks (async via AgentTask)."""
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

    if secret:
        if not verify_email_signature(secret, payload, signature):
            return JSONResponse(
                status_code=403,
                content={"status": "unauthorized", "reason": "invalid_signature"},
            )
    elif _STRICT_MODE:
        return JSONResponse(
            status_code=403,
            content={"status": "unauthorized", "reason": "no_email_secret_strict_mode"},
        )
    
    return ingest_email_webhook_event(session, payload, forced_company_id=company_id)

    # if not company_id:
    #     return {"status": "ignored", "reason": "company_not_found"}

    # from services.agent.agent_task_service import create_agent_task
    # create_agent_task(
    #     session=session,
    #     company_id=company_id,
    #     task_type="process_inbound_email",
    #     assigned_agent="webhook_handlers",
    #     input_json={"payload": payload, "forced_company_id": company_id},
    #     idempotency_key=f"email_inbound:{payload.get('Message-ID') or hash(json.dumps(payload))}",
    #     requires_approval=False,
    # )
    # return {"status": "queued"}


@router.post("/quote/accept/{token}")
async def public_accept_quote(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"quote_accept:{ip}", limit=5, window_seconds=60):
        return _rate_limit_response()
    quote = respond_to_quote_token(session, token, "accept")
    return {"status": "accepted", "quote_id": quote.id, "quote_number": quote.quote_number}


@router.post("/quote/reject/{token}")
async def public_reject_quote(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"quote_reject:{ip}", limit=5, window_seconds=60):
        return _rate_limit_response()
    quote = respond_to_quote_token(session, token, "reject")
    return {"status": "rejected", "quote_id": quote.id, "quote_number": quote.quote_number}


@router.post("/quote/negotiate/{token}")
async def public_negotiate_quote(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"quote_negotiate:{ip}", limit=5, window_seconds=60):
        return _rate_limit_response()
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        return JSONResponse(status_code=400, content={"detail": "Message is required"})
    requested_discount = body.get("requested_discount")
    if requested_discount is not None:
        try:
            requested_discount = float(requested_discount)
        except (TypeError, ValueError):
            requested_discount = None
    return negotiate_quote_by_token(session, token, message, requested_discount)


@router.get("/quote/info/{token}")
async def public_quote_info(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
):
    ip = _client_ip(request)
    if _is_rate_limited(key=f"quote_info:{ip}", limit=30, window_seconds=60):
        return _rate_limit_response()
    return get_public_quote_info(session, token)