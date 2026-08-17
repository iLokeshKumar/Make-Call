from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

from fastapi import HTTPException
from sqlmodel import Session, select
from twilio.rest import Client as TwilioClient
from twilio.base.exceptions import TwilioRestException

from credentials_service import get_company_credential, get_company_setting_value
from models.models import CallTask, Company, Interaction, Lead, OptOut, User, utc_now
from services.call.outbound_call_service import create_call_task, get_call_task_or_404, start_call_task
from utils.phone import normalize_phone
from utils.url_utils import normalize_base_url
from utils.timezone_utils import (
    business_hours_config_for_company,
    is_within_business_hours,
    resolve_lead_timezone,
)
from services.leads.opt_out_service import is_lead_opted_out
from services.core.usage_service import check_and_increment
from services.core.feature_flag_service import require_feature

def is_lead_callable(session: Session, company_id: int, lead_id: int) -> tuple[bool, str | None]:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        return False, "lead_not_found"
    if not lead.normalized_phone:
        return False, "missing_phone"

    if is_lead_opted_out(session, company_id, lead_id, "call"):
        return False, "opted_out"

    if (lead.status or "").lower() in {"closed_won", "closed_lost", "do_not_call"}:
        return False, "lead_closed"

    tz_str = resolve_lead_timezone(lead, session=session, company_id=company_id)
    bh = business_hours_config_for_company(session, company_id)
    if not is_within_business_hours(
        tz_str,
        start_hour=bh["start"],
        end_hour=bh["end"],
        sunday_blocked=bh["sunday_blocked"],
        disabled=bh["disabled"],
    ):
        return False, f"outside_business_hours:{tz_str}"

    return True, None


def opt_out_lead_from_calls(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    reason: str | None = None,
) -> OptOut:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    existing = session.exec(
        select(OptOut).where(
            OptOut.company_id == company_id,
            OptOut.lead_id == lead_id,
            OptOut.channel == "call",
        )
    ).first()
    if existing:
        return existing

    opt_out = OptOut(
        company_id=company_id,
        lead_id=lead_id,
        channel="call",
        reason=reason,
    )
    session.add(opt_out)
    lead.status = "do_not_call"
    lead.updated_at = utc_now()
    lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()
    session.refresh(opt_out)
    return opt_out


def create_batch_call_tasks(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_ids: list[int],
    assigned_user_id: int | None = None,
    batch_id: str | None = None,
    scheduled_at=None,
    notes: str | None = None,
    dialer_source: str = "batch_dialer",
) -> dict:
    created: list[int] = []
    skipped: list[dict[str, str | int]] = []
    normalized_batch_id = batch_id or f"batch-{utc_now().strftime('%Y%m%d%H%M%S')}"

    for lead_id in lead_ids:
        callable_lead, reason = is_lead_callable(session, company_id, lead_id)
        if not callable_lead:
            skipped.append({"lead_id": lead_id, "reason": reason or "not_callable"})
            continue

        task = create_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            assigned_user_id=assigned_user_id,
            scheduled_at=scheduled_at,
            notes=notes,
            batch_id=normalized_batch_id,
            dialer_source=dialer_source,
            initial_status="queued",
        )
        created.append(task.id)

    return {
        "batch_id": normalized_batch_id,
        "created_task_ids": created,
        "created_count": len(created),
        "skipped": skipped,
    }


def get_next_queued_task(session: Session, company_id: int) -> CallTask | None:
    now = utc_now()
    return session.exec(
        select(CallTask).where(
            CallTask.company_id == company_id,
            CallTask.status.in_(["queued", "retry_scheduled"]),
            (CallTask.scheduled_at.is_(None)) | (CallTask.scheduled_at <= now),
            (CallTask.retry_after.is_(None)) | (CallTask.retry_after <= now),
        ).order_by(CallTask.created_at.asc())
    ).first()


def _resolve_callback_base(session: Session, company_id: int) -> str:
    if env_domain := os.getenv("DOMAIN"):
        return normalize_base_url(env_domain, "https://localhost:8000")
    company = session.get(Company, company_id)
    domain_source = (company.domain if company and company.domain else None) or "localhost:8000"
    return normalize_base_url(domain_source, "https://localhost:8000")


def get_telephony_engine(session: Session, company_id: int) -> str:
    """Read the company's configured telephony engine (twilio/plivo/vobiz/enablex/exotel)."""
    val = get_company_setting_value(session, company_id, "TELEPHONY_ENGINE")
    return (val or "twilio").lower()


def _initiate_twilio_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    normalized_to: str,
    lead_id: int | None,
    call_task_id: int | None,
    agent_id: int | None,
    interaction: Interaction,
    actor_user: User | None,
) -> dict:
    account_sid = get_company_credential(session, company_id, "TWILIO_ACCOUNT_SID")
    auth_token = get_company_credential(session, company_id, "TWILIO_AUTH_TOKEN")
    from_number = (
        get_company_credential(session, company_id, "TWILIO_PHONE_NUMBER")
        or os.getenv("PHONE_NUMBER_FROM")
    )
    if not all([account_sid, auth_token, from_number]):
        raise HTTPException(status_code=400, detail="Twilio credentials are not configured")

    callback_base = _resolve_callback_base(session, company_id)
    call_url = (
        f"{callback_base}/outgoing-call"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}"
    )
    if agent_id:
        call_url += f"&agent_id={agent_id}"

    status_callback = (
        f"{callback_base}/twilio/status-callback"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}"
    )
    if agent_id:
        status_callback += f"&agent_id={agent_id}"

    recording_callback = (
        f"{callback_base}/twilio/recording-callback"
        f"?interaction_id={interaction.id}"
    )

    require_feature(session, company_id, "outbound_calls")
    check_and_increment(session, company_id, "calls_made")

    client = TwilioClient(account_sid, auth_token)
    try:
        call = client.calls.create(
            to=normalized_to,
            from_=from_number,
            url=call_url,
            status_callback=status_callback,
            status_callback_event=["initiated", "ringing", "in-progress", "completed", "busy", "no-answer", "failed", "canceled"],
            status_callback_method="POST",
            record=True,
            recording_status_callback=recording_callback,
            recording_status_callback_method="POST",
        )
    except TwilioRestException as exc:
        if exc.code in (20003, 20005):
            raise HTTPException(
                status_code=402,
                detail=f"Twilio account error ({exc.code}): {exc.msg}. Check credentials or account balance.",
            )
        if exc.code == 21219:
            raise HTTPException(
                status_code=402,
                detail=(
                    f"Twilio trial restriction ({exc.code}): '{normalized_to}' is not a verified number. "
                    "Trial accounts can only call numbers verified in the Twilio console — add the number "
                    "under Phone Numbers → Verified Caller IDs, or upgrade the account (Billing → Upgrade) "
                    "to call any number."
                ),
            )
        if exc.code in (21210, 21211, 21214, 21604):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid phone number '{normalized_to}': {exc.msg}",
            )
        raise HTTPException(status_code=503, detail=f"Twilio error {exc.code}: {exc.msg}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to initiate call: {exc}")

    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "call_sid": call.sid,
        "to": normalized_to,
    }
    session.add(interaction)

    lead = session.get(Lead, lead_id) if lead_id else None
    if lead:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)

    session.commit()

    logger.info("outbound call initiated", extra={
        "event": "outbound_call_initiated",
        "company_id": company_id,
        "lead_id": lead_id,
        "call_sid": call.sid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "worker_name": "dialer",
    })

    return {
        "status": "initiated",
        "call_sid": call.sid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "lead_id": lead_id,
        "user_id": actor_user.id if actor_user else actor_user_id,
    }


def _initiate_plivo_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    normalized_to: str,
    lead_id: int | None,
    call_task_id: int | None,
    agent_id: int | None,
    interaction: Interaction,
    actor_user: User | None,
) -> dict:
    auth_id = get_company_credential(session, company_id, "PLIVO_AUTH_ID")
    auth_token = get_company_credential(session, company_id, "PLIVO_AUTH_TOKEN")
    from_number = get_company_credential(session, company_id, "PLIVO_PHONE_NUMBER")
    if not all([auth_id, auth_token, from_number]):
        raise HTTPException(status_code=400, detail="Plivo credentials are not configured")

    callback_base = _resolve_callback_base(session, company_id)
    answer_url = (
        f"{callback_base}/plivo-answer"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}&agent_id={agent_id or 0}"
    )

    from plivo import RestClient
    client = RestClient(auth_id=auth_id, auth_token=auth_token)
    try:
        response = client.calls.create(
            from_=from_number,
            to=normalized_to,
            answer_url=answer_url,
            answer_method="POST",
        )
    except Exception as exc:
        err_msg = str(exc)
        if "20003" in err_msg or "20005" in err_msg:
            raise HTTPException(status_code=402, detail=f"Plivo account error: {err_msg[:200]}")
        raise HTTPException(status_code=503, detail=f"Failed to initiate Plivo call: {err_msg[:300]}")

    call_uuid = getattr(response, "request_uuid", "") or ""
    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "call_sid": call_uuid,
        "to": normalized_to,
    }
    session.add(interaction)

    lead = session.get(Lead, lead_id) if lead_id else None
    if lead:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)

    session.commit()

    logger.info("[Dialer] Plivo call initiated", extra={
        "event": "outbound_call_initiated", "company_id": company_id, "lead_id": lead_id,
        "call_sid": call_uuid, "interaction_id": interaction.id, "call_task_id": call_task_id,
        "agent_id": agent_id, "worker_name": "dialer", "provider": "plivo",
    })

    return {
        "status": "initiated",
        "call_sid": call_uuid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "agent_id": agent_id,
        "lead_id": lead_id,
        "user_id": actor_user.id if actor_user else actor_user_id,
    }


def _initiate_vobiz_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    normalized_to: str,
    lead_id: int | None,
    call_task_id: int | None,
    agent_id: int | None,
    interaction: Interaction,
    actor_user: User | None,
) -> dict:
    import urllib.request
    import json
    import ssl

    auth_id = get_company_credential(session, company_id, "VOBIZ_AUTH_ID")
    auth_token = get_company_credential(session, company_id, "VOBIZ_AUTH_TOKEN")
    from_number = get_company_credential(session, company_id, "VOBIZ_PHONE_NUMBER")
    if not all([auth_id, auth_token, from_number]):
        raise HTTPException(status_code=400, detail="Vobiz credentials are not configured")

    callback_base = _resolve_callback_base(session, company_id)
    answer_url = (
        f"{callback_base}/vobiz-answer"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}&agent_id={agent_id or 0}"
    )

    vobiz_host = "api.vobiz.ai"
    vobiz_url = f"https://{vobiz_host}/api/v1/Account/{auth_id}/Call/"

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        status_callback_url = (
            f"{callback_base}/vobiz/status-callback"
            f"?user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}"
        )
        req_data = json.dumps({
            "from": from_number,
            "to": normalized_to,
            "answer_url": answer_url,
            "answer_method": "POST",
            "status_url": status_callback_url,
            "status_method": "POST",
        }).encode("utf-8")

        req = urllib.request.Request(
            vobiz_url,
            data=req_data,
            headers={
                "X-Auth-ID": auth_id,
                "X-Auth-Token": auth_token,
                "Content-Type": "application/json",
            },
            method="POST"
        )

        with urllib.request.urlopen(req, context=ctx, timeout=30) as response:
            resp_body = response.read().decode("utf-8")
            result = json.loads(resp_body)
    except urllib.error.HTTPError as exc:
        detail = f"Vobiz API error (HTTP {exc.code}): {exc.read().decode('utf-8')[:200]}"
        raise HTTPException(status_code=exc.code or 503, detail=detail)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error(f"[Dialer] Failed to initiate Vobiz call: {exc}\n{tb}")
        raise HTTPException(status_code=503, detail=f"Failed to initiate Vobiz call: {exc} | Traceback: {tb}")

    call_uuid = result.get("call_uuid") or result.get("request_uuid") or ""

    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "call_sid": call_uuid,
        "to": normalized_to,
    }
    session.add(interaction)

    lead = session.get(Lead, lead_id) if lead_id else None
    if lead:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)

    session.commit()

    logger.info("[Dialer] Vobiz call initiated", extra={
        "event": "outbound_call_initiated", "company_id": company_id, "lead_id": lead_id,
        "call_sid": call_uuid, "interaction_id": interaction.id, "call_task_id": call_task_id,
        "agent_id": agent_id, "worker_name": "dialer", "provider": "vobiz",
    })

    return {
        "status": "initiated",
        "call_sid": call_uuid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "agent_id": agent_id,
        "lead_id": lead_id,
        "user_id": actor_user.id if actor_user else actor_user_id,
    }


def _initiate_enablex_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    normalized_to: str,
    lead_id: int | None,
    call_task_id: int | None,
    agent_id: int | None,
    interaction: Interaction,
    actor_user: User | None,
) -> dict:
    import urllib.request
    import urllib.parse
    import json
    import base64

    app_id = get_company_credential(session, company_id, "ENABLEX_APP_ID")
    app_key = get_company_credential(session, company_id, "ENABLEX_APP_KEY")
    from_number = get_company_credential(session, company_id, "ENABLEX_FROM_NUMBER")
    if not all([app_id, app_key, from_number]):
        raise HTTPException(status_code=400, detail="EnableX credentials not configured (need ENABLEX_APP_ID, ENABLEX_APP_KEY, ENABLEX_FROM_NUMBER)")

    callback_base = _resolve_callback_base(session, company_id)

    # EnableX calls our WebSocket when call connects (same pattern as Twilio <Stream>)
    ws_base = callback_base.replace("https://", "wss://").replace("http://", "ws://")
    stream_url = (
        f"{ws_base}/enablex-media-stream"
        f"?user_id={actor_user_id}&lead_id={lead_id or 0}"
        f"&interaction_id={interaction.id}&call_task_id={call_task_id or 0}&agent_id={agent_id or 0}"
    )
    event_url = (
        f"{callback_base}/enablex/event"
        f"?user_id={actor_user_id}&interaction_id={interaction.id}&call_task_id={call_task_id or 0}"
    )

    body = json.dumps({
        "name": "RIO_CRM",
        "from": from_number,
        "to": normalized_to,
        "action_on_connect": {
            "stream": {
                "url": stream_url,
                "bidirectional": True,
                "sample_rate": 8000,
            }
        },
        "event_url": event_url,
    }).encode("utf-8")

    credentials = base64.b64encode(f"{app_id}:{app_key}".encode()).decode()
    req = urllib.request.Request(
        "https://api.enablex.io/voice/v1/call",
        data=body,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode("utf-8")[:300]
        raise HTTPException(status_code=exc.code or 503, detail=f"EnableX API error: {body_err}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to initiate EnableX call: {exc}")

    voice_id = result.get("voice_id") or result.get("call_id") or ""

    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "call_sid": voice_id,
        "to": normalized_to,
    }
    session.add(interaction)

    lead = session.get(Lead, lead_id) if lead_id else None
    if lead:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)

    session.commit()

    logger.info("[Dialer] EnableX call initiated", extra={
        "event": "outbound_call_initiated", "company_id": company_id, "lead_id": lead_id,
        "call_sid": voice_id, "interaction_id": interaction.id, "call_task_id": call_task_id,
        "agent_id": agent_id, "worker_name": "dialer", "provider": "enablex",
    })

    return {
        "status": "initiated",
        "call_sid": voice_id,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "agent_id": agent_id,
        "lead_id": lead_id,
        "user_id": actor_user.id if actor_user else actor_user_id,
    }


def _initiate_exotel_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    normalized_to: str,
    lead_id: int | None,
    call_task_id: int | None,
    agent_id: int | None,
    interaction: Interaction,
    actor_user: User | None,
) -> dict:
    import urllib.request
    import urllib.parse
    import json

    api_key = get_company_credential(session, company_id, "EXOTEL_API_KEY")
    api_token = get_company_credential(session, company_id, "EXOTEL_API_TOKEN")
    account_sid = get_company_credential(session, company_id, "EXOTEL_ACCOUNT_SID")
    exophone = get_company_credential(session, company_id, "EXOPHONE")
    if not all([api_key, api_token, account_sid, exophone]):
        raise HTTPException(status_code=400, detail="Exotel credentials are not configured (need EXOTEL_API_KEY, EXOTEL_API_TOKEN, EXOTEL_ACCOUNT_SID, EXOPHONE)")

    callback_base = _resolve_callback_base(session, company_id)
    answer_url = (
        f"{callback_base}/exotel-answer"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}"
        f"&call_task_id={call_task_id or 0}&agent_id={agent_id or 0}"
    )
    status_callback = (
        f"{callback_base}/exotel/status-callback"
        f"?lead_id={lead_id or 0}&user_id={actor_user_id}&interaction_id={interaction.id}"
        f"&call_task_id={call_task_id or 0}"
    )

    # Strip leading '+' — Exotel expects numeric format
    caller_id = exophone.lstrip("+")
    to_number = normalized_to.lstrip("+")

    recording_callback = f"{callback_base}/exotel/recording-callback?interaction_id={interaction.id}"

    api_url = f"https://api.exotel.com/v1/Accounts/{account_sid}/Calls/connect.json"
    post_data = urllib.parse.urlencode({
        "From": to_number,
        "CallerId": caller_id,
        "Url": answer_url,
        "CallType": "trans",
        "TimeLimit": "120",
        "TimeOut": "30",
        "StatusCallback": status_callback,
        "StatusCallbackMethod": "POST",
        "Record": "true",
        "RecordingStatusCallback": recording_callback,
        "RecordingStatusCallbackMethod": "POST",
    }).encode("utf-8")

    import base64
    credentials = base64.b64encode(f"{api_key}:{api_token}".encode()).decode()
    req = urllib.request.Request(
        api_url,
        data=post_data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            err = json.loads(body)
            code = err.get("RestException", {}).get("Code")
            msg = err.get("RestException", {}).get("Message", body[:200])
        except Exception:
            code, msg = None, body[:200]
        if code == 34010:
            raise HTTPException(status_code=401, detail=f"Exotel auth failed (34010): {msg}")
        if code == 34001:
            raise HTTPException(status_code=400, detail=f"Exotel Exophone not active (34001): {msg}")
        raise HTTPException(status_code=exc.code or 503, detail=f"Exotel API error ({code}): {msg}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Failed to initiate Exotel call: {exc}")

    call_sid = result.get("Call", {}).get("Sid", "")

    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "call_sid": call_sid,
        "to": normalized_to,
    }
    session.add(interaction)

    lead = session.get(Lead, lead_id) if lead_id else None
    if lead:
        lead.last_outreach_at = utc_now()
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)

    session.commit()

    logger.info("[Dialer] Exotel call initiated", extra={
        "event": "outbound_call_initiated", "company_id": company_id, "lead_id": lead_id,
        "call_sid": call_sid, "interaction_id": interaction.id, "call_task_id": call_task_id,
        "agent_id": agent_id, "worker_name": "dialer", "provider": "exotel",
    })

    return {
        "status": "initiated",
        "call_sid": call_sid,
        "interaction_id": interaction.id,
        "call_task_id": call_task_id,
        "agent_id": agent_id,
        "lead_id": lead_id,
        "user_id": actor_user.id if actor_user else actor_user_id,
    }


def initiate_outbound_call(
    session: Session,
    company_id: int,
    actor_user_id: int,
    to: str,
    lead_id: Optional[int] = None,
    call_task_id: Optional[int] = None,
    agent_id: Optional[int] = None,
) -> dict:
    normalized_to = normalize_phone(to)

    # Pre-call workflow via orchestrator (knowledge search + enrichment + ICP score)
    enable_precall_researcher = os.getenv("ENABLE_PRECALL_RESEARCHER", "1").lower() in {"1", "true", "yes", "on"}
    if lead_id and enable_precall_researcher:
        precall_timeout_s = float(os.getenv("PRECALL_TIMEOUT_S", "4.0"))

        async def _run_precall():
            from agents.orchestrator import run_pre_call
            from utils.precall_cache import put as cache_put
            result = await asyncio.wait_for(
                run_pre_call(
                    lead_id=lead_id,
                    company_id=company_id,
                    actor_user_id=actor_user_id,
                ),
                timeout=precall_timeout_s,
            )
            cache_put(company_id, lead_id, result)
            logger.info(
                "[Dialer] Pre-call complete for lead %s: icp=%.2f, kb_chunks=%d",
                lead_id,
                result.get("icp_score", 0.0),
                len(result.get("kb_context", [])),
            )

        try:
            import asyncio
            import concurrent.futures
            import contextvars
            try:
                asyncio.get_running_loop()
                ctx = contextvars.copy_context()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    pool.submit(ctx.run, asyncio.run, _run_precall()).result()
            except RuntimeError:
                asyncio.run(_run_precall())
        except asyncio.TimeoutError:
            logger.warning(
                "[Dialer] Pre-call exceeded %.1fs budget for lead %s — dialing without KB context",
                precall_timeout_s, lead_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Dialer] Pre-call workflow failed (non-blocking): %s", exc)

    lead = None
    if lead_id:
        allowed, reason = is_lead_callable(session, company_id, lead_id)
        if not allowed:
            raise HTTPException(status_code=400, detail=f"Lead is not callable: {reason}")
        lead = session.exec(
            select(Lead).where(
                Lead.id == lead_id,
                Lead.company_id == company_id,
            )
        ).first()
    else:
        lead = session.exec(
            select(Lead).where(
                Lead.company_id == company_id,
                Lead.normalized_phone == normalized_to,
            )
        ).first()
        if lead:
            allowed, reason = is_lead_callable(session, company_id, lead.id)
            if not allowed:
                raise HTTPException(status_code=400, detail=f"Lead is not callable: {reason}")
            lead_id = lead.id

    actor_user = session.get(User, actor_user_id)

    # Read telephony engine setting (twilio / plivo / exotel / vobiz)
    engine = get_telephony_engine(session, company_id)
    if agent_id:
        from models.models import VoiceAgentRuntimeConfig
        runtime = session.exec(
            select(VoiceAgentRuntimeConfig).where(VoiceAgentRuntimeConfig.agent_id == agent_id)
        ).first()
        if runtime and runtime.telephony_engine:
            engine = runtime.telephony_engine.lower()

    interaction = Interaction(
        company_id=company_id,
        lead_id=lead_id,
        user_id=actor_user_id,
        type="call",
        channel="call",
        direction="outbound",
        source=engine,
        content="Outbound Call",
        status="active",
        started_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(interaction)
    session.commit()
    session.refresh(interaction)

    if call_task_id:
        start_call_task(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            task_id=call_task_id,
            interaction_id=interaction.id,
        )

    # Delegate call initiation based on engine
    if engine == "plivo":
        return _initiate_plivo_call(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            normalized_to=normalized_to,
            lead_id=lead_id,
            call_task_id=call_task_id,
            agent_id=agent_id,
            interaction=interaction,
            actor_user=actor_user,
        )
    elif engine == "vobiz":
        return _initiate_vobiz_call(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            normalized_to=normalized_to,
            lead_id=lead_id,
            call_task_id=call_task_id,
            agent_id=agent_id,
            interaction=interaction,
            actor_user=actor_user,
        )
    elif engine == "enablex":
        return _initiate_enablex_call(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            normalized_to=normalized_to,
            lead_id=lead_id,
            call_task_id=call_task_id,
            agent_id=agent_id,
            interaction=interaction,
            actor_user=actor_user,
        )
    elif engine == "exotel":
        return _initiate_exotel_call(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            normalized_to=normalized_to,
            lead_id=lead_id,
            call_task_id=call_task_id,
            agent_id=agent_id,
            interaction=interaction,
            actor_user=actor_user,
        )
    else:
        return _initiate_twilio_call(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            normalized_to=normalized_to,
            lead_id=lead_id,
            call_task_id=call_task_id,
            agent_id=agent_id,
            interaction=interaction,
            actor_user=actor_user,
        )


def execute_call_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task_id: int,
) -> dict:
    task = get_call_task_or_404(session, company_id, task_id)
    allowed, reason = is_lead_callable(session, company_id, task.lead_id)
    if not allowed:
        raise HTTPException(status_code=400, detail=f"Lead is not callable: {reason}")

    lead = session.exec(
        select(Lead).where(
            Lead.id == task.lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    actor_id = task.assigned_user_id or actor_user_id
    return initiate_outbound_call(
        session=session,
        company_id=company_id,
        actor_user_id=actor_id,
        to=lead.normalized_phone,
        lead_id=lead.id,
        call_task_id=task.id,
    )


def schedule_retry_for_task(
    session: Session,
    company_id: int,
    actor_user_id: int,
    task: CallTask,
    retry_after_hours: int,
    reason: str,
) -> CallTask:
    task.status = "retry_scheduled"
    from datetime import timedelta

    task.retry_after = utc_now() + timedelta(hours=retry_after_hours)
    task.scheduled_at = task.retry_after
    task.notes = ((task.notes or "").strip() + f"\nRetry scheduled: {reason}").strip()
    task.updated_at = utc_now()
    task.updated_by = actor_user_id
    session.add(task)
    session.commit()
    session.refresh(task)
    return task


def run_batch_dialer(
    session: Session,
    company_id: int,
    actor_user_id: int,
    limit: int = 20,
) -> list[dict]:
    # Per-minute rate limit — read from company settings (DIALER_CALLS_PER_MINUTE). Default: 10 calls/min → one call every 6 s.  Set to 0 to disable throttling.
    cpm_raw = get_company_setting_value(session, company_id, "DIALER_CALLS_PER_MINUTE")
    try:
        calls_per_minute = max(0, int(cpm_raw or 10))
    except (TypeError, ValueError):
        calls_per_minute = 10
    inter_call_delay = (60.0 / calls_per_minute) if calls_per_minute > 0 else 0.0

    results: list[dict] = []
    for call_count in range(limit):
        task = get_next_queued_task(session, company_id)
        if not task:
            break

        # Throttle: wait before firing the second and subsequent calls
        if call_count > 0 and inter_call_delay > 0:
            time.sleep(inter_call_delay)

        try:
            result = execute_call_task(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                task_id=task.id,
            )
            logger.info("call task executed", extra={
                "event": "call_task_executed",
                "company_id": company_id,
                "task_id": task.id,
                "call_sid": result.get("call_sid"),
                "worker_name": "dialer",
            })
            results.append({"success": True, "task_id": task.id, "result": result})
        except Exception as exc:
            logger.exception("call task failed", extra={
                "event": "call_task_failed",
                "company_id": company_id,
                "task_id": task.id,
                "error": str(exc),
                "worker_name": "dialer",
            })
            task.status = "failed"
            task.last_outcome = "failed"
            task.updated_at = utc_now()
            task.updated_by = actor_user_id
            session.add(task)
            session.commit()
            results.append({"success": False, "task_id": task.id, "error": str(exc)})
    return results


async def poll_vobiz_recording(
    company_id: int,
    interaction_id: int,
    call_uuid: str,
    max_retries: int = 20,
    retry_delay: int = 15,
) -> None:
    """Poll Vobiz Recording API for the call's recording URL.

    Fires as a background task after the call ends when the callback
    hasn't arrived yet.  Polls every *retry_delay* seconds up to
    *max_retries * retry_delay* seconds total (~5 minutes with defaults).
    """
    import asyncio
    import httpx

    from database import engine as _db_engine
    from sqlmodel import Session as _Session
    from models.models import Interaction

    # Vobiz API may use different field names across versions.
    # Try all known aliases.
    _URL_FIELDS = ("recording_url", "record_url", "RecordUrl", "RecordFile", "url")
    _DUR_FIELDS = ("recording_duration_ms", "duration_ms", "duration")
    _SID_FIELDS = ("recording_id", "RecordingID", "id")

    for attempt in range(1, max_retries + 1):
        try:
            with _Session(_db_engine) as session:
                # If a previous callback already saved the URL, stop polling.
                interaction_check = session.get(Interaction, interaction_id)
                if interaction_check and interaction_check.recording_url:
                    logger.info(
                        "[VobizRecordPoll] Recording already set for interaction %s — stopping poll",
                        interaction_id,
                    )
                    return

                auth_id = get_company_credential(session, company_id, "VOBIZ_AUTH_ID")
                auth_token = get_company_credential(session, company_id, "VOBIZ_AUTH_TOKEN")
                if not auth_id or not auth_token:
                    logger.warning("[VobizRecordPoll] Vobiz credentials not found for company %s", company_id)
                    return

                url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Recording/?call_uuid={call_uuid}"
                headers = {
                    "X-Auth-ID": auth_id,
                    "X-Auth-Token": auth_token,
                    "Content-Type": "application/json",
                }

                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(url, headers=headers)

                if resp.status_code == 200:
                    data = resp.json()
                    objects = data.get("objects") or data.get("recordings") or []
                    logger.info(
                        "[VobizRecordPoll] Attempt %d/%d — status=200 objects=%d top_keys=%s",
                        attempt, max_retries, len(objects),
                        list(data.keys()) if isinstance(data, dict) else "non-dict",
                    )
                    if objects:
                        rec = objects[0]
                        logger.info("[VobizRecordPoll] rec fields: %s", list(rec.keys()) if isinstance(rec, dict) else rec)
                        recording_url = next((rec.get(f) for f in _URL_FIELDS if rec.get(f)), None)
                        if recording_url:
                            dur_raw = next((rec.get(f) for f in _DUR_FIELDS if rec.get(f)), None)
                            rec_sid = next((rec.get(f) for f in _SID_FIELDS if rec.get(f)), "")
                            with _Session(_db_engine) as update_session:
                                interaction = update_session.get(Interaction, interaction_id)
                                if interaction and not interaction.recording_url:
                                    interaction.recording_url = recording_url
                                    if dur_raw:
                                        try:
                                            dur_float = float(dur_raw)
                                            # duration_ms → seconds; plain seconds stay as-is
                                            interaction.recording_duration = int(
                                                dur_float / 1000 if dur_float > 3600 else dur_float
                                            )
                                        except (ValueError, TypeError):
                                            pass
                                    interaction.metadata_json = {
                                        **(interaction.metadata_json or {}),
                                        "recording_sid": str(rec_sid),
                                    }
                                    interaction.updated_at = utc_now()
                                    update_session.add(interaction)
                                    update_session.commit()
                                    logger.info(
                                        "[VobizRecordPoll] Recording saved for interaction %s — %s",
                                        interaction_id, recording_url,
                                    )
                                return  # success
                        else:
                            logger.info(
                                "[VobizRecordPoll] objects present but no URL field found; rec keys: %s",
                                list(rec.keys()) if isinstance(rec, dict) else rec,
                            )
                    # objects empty → recording not ready yet, keep retrying
                else:
                    logger.warning(
                        "[VobizRecordPoll] Attempt %d/%d — unexpected status %d for interaction %s",
                        attempt, max_retries, resp.status_code, interaction_id,
                    )
        except Exception as exc:
            logger.warning(
                "[VobizRecordPoll] Attempt %d/%d failed for interaction %s: %s",
                attempt, max_retries, interaction_id, exc,
            )

        if attempt < max_retries:
            await asyncio.sleep(retry_delay)

    logger.warning(
        "[VobizRecordPoll] Exhausted %d retries for interaction %s (call %s)",
        max_retries, interaction_id, call_uuid,
    )
