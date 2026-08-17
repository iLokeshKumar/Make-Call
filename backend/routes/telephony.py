import logging
import os
from html import escape
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session, select
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Connect, Dial, Gather, Hangup, VoiceResponse

from auth import PermissionChecker, get_current_user
from communicators import BrowserCommunicator, EnableXCommunicator, ExotelCommunicator, TwilioCommunicator, PlivoCommunicator, VobizCommunicator
from credentials_service import get_company_credential, get_company_setting_value
from database import get_session
from models.models import CallTask, Company, Interaction, Lead, User, VoiceAgentRuntimeConfig, utc_now
from sqlmodel import select as sql_select
from services.campaign.dialer_service import initiate_outbound_call
from services.call.outcome_service import apply_call_outcome, apply_lead_only_outcome
from services.call.outbound_call_service import start_call_task
from services.call.warm_transfer_service import execute_warm_transfer
from utils.phone import normalize_phone
from utils.url_utils import normalize_base_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Telephony"])


def _trigger_vobiz_recording(session: Session, company_id: int, interaction_id: int, call_uuid: str, callback_base: str) -> dict:
    """POST to Vobiz Record API to start recording.

    Returns the 202 response dict (contains recording_id and provisional url)
    or {} on failure.
    """
    import json
    import ssl
    import urllib.request

    auth_id = get_company_credential(session, company_id, "VOBIZ_AUTH_ID")
    auth_token = get_company_credential(session, company_id, "VOBIZ_AUTH_TOKEN")
    if not auth_id or not auth_token:
        logger.warning("[Vobiz] Cannot start recording — credentials missing for company %s", company_id)
        return {}

    record_url = f"https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/{call_uuid}/Record/"
    record_data = json.dumps({
        "time_limit": 3600,
        "file_format": "mp3",
        "callback_url": f"{callback_base}/vobiz/recording-callback?interaction_id={interaction_id}",
        "callback_method": "POST",
    }).encode("utf-8")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        record_url,
        data=record_data,
        headers={
            "X-Auth-ID": auth_id,
            "X-Auth-Token": auth_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            body = resp.read().decode("utf-8")
            result = json.loads(body) if body else {}
            logger.info(
                "[Vobiz] Recording started — call=%s interaction=%s recording_id=%s",
                call_uuid, interaction_id, result.get("recording_id"),
            )
            return result
    except Exception as exc:
        logger.error("[Vobiz] Failed to start recording for call %s: %s", call_uuid, exc)
        return {}


def _trigger_enablex_recording(session: Session, company_id: int, interaction_id: int, voice_id: str, callback_base: str) -> None:
    """Call EnableX Record API to start recording after the call is answered."""
    import base64
    import json
    import urllib.request

    app_id = get_company_credential(session, company_id, "ENABLEX_APP_ID")
    app_key = get_company_credential(session, company_id, "ENABLEX_APP_KEY")
    if not app_id or not app_key:
        logger.warning("[EnableX] Cannot start recording — credentials missing for company %s", company_id)
        return

    record_url = f"https://api.enablex.io/voice/v1/call/{voice_id}/record"
    record_data = json.dumps({
        "file_format": "mp3",
        "callback_url": f"{callback_base}/enablex/recording-callback?interaction_id={interaction_id}",
    }).encode("utf-8")

    credentials = base64.b64encode(f"{app_id}:{app_key}".encode()).decode()
    req = urllib.request.Request(
        record_url,
        data=record_data,
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10):
            logger.info("[EnableX] Recording started for call %s (interaction %s)", voice_id, interaction_id)
    except Exception as exc:
        logger.error("[EnableX] Failed to start recording for call %s: %s", voice_id, exc)


def get_communicator_for_source(source: str, websocket):
    if source == "browser":
        return BrowserCommunicator(websocket)
    if source == "enablex":
        return EnableXCommunicator(websocket)
    if source == "exotel":
        return ExotelCommunicator(websocket)
    if source == "plivo":
        return PlivoCommunicator(websocket)
    if source == "vobiz":
        return VobizCommunicator(websocket)
    return TwilioCommunicator(websocket)


def _get_connect_message(session: Session, company_id: int, company_name: str) -> str:
    """Read CALL_CONNECT_MESSAGE from company settings, fall back to default."""
    template = get_company_setting_value(session, company_id, "CALL_CONNECT_MESSAGE") or ""
    if template:
        return template.replace("{company_name}", company_name)
    return f"Connected to {company_name}. Please start speaking."


def _build_ai_connect_response(request: Request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name: str, connect_message: str = "") -> VoiceResponse:
    """Build TwiML <Connect><Stream> for AI voice pipeline."""
    response = VoiceResponse()
    response.say(connect_message or f"Connected to {company_name}. Please start speaking.")
    connect = Connect()
    stream = connect.stream(
        url=(
            f"wss://{request.url.netloc}/media-stream"
            f"?user_id={user_id or 0}&lead_id={lead_id or 0}&interaction_id={interaction_id or ''}&call_task_id={call_task_id}&agent_id={agent_id or 0}"
        )
    )
    stream.parameter(name="user_id", value=str(user_id or 0))
    stream.parameter(name="lead_id", value=str(lead_id or 0))
    stream.parameter(name="interaction_id", value=str(interaction_id or ""))
    stream.parameter(name="call_task_id", value=str(call_task_id))
    stream.parameter(name="agent_id", value=str(agent_id or 0))
    response.append(connect)
    return response


def _build_plivo_connect_response(request: Request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name: str, connect_message: str = "") -> str:
    """Build Plivo XML <Response> with <Stream> for AI voice pipeline."""
    ws_url = (
        f"wss://{request.url.netloc}/plivo-media-stream"
        f"?user_id={user_id or 0}&lead_id={lead_id or 0}&interaction_id={interaction_id or ''}&call_task_id={call_task_id}&agent_id={agent_id or 0}"
    )
    msg = connect_message or f"Connected to {company_name}. Please start speaking."
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response>'
        f'<Speak>{msg}</Speak>'
        f'<Stream bidirectional="true" keepCallAlive="true" contentType="audio/mulaw;rate=8000">'
        f'{ws_url}'
        f'</Stream>'
        f'</Response>'
    )


def _build_vobiz_connect_response(request: Request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name: str, connect_message: str = "") -> str:
    """Build Vobiz XML with bidirectional stream for AI voice pipeline."""
    ws_url = (
        f"wss://{request.url.netloc}/vobiz-media-stream"
        f"?user_id={user_id or 0}&lead_id={lead_id or 0}&interaction_id={interaction_id or ''}&call_task_id={call_task_id}&agent_id={agent_id or 0}"
    )
    recording_callback = (
        f"{request.url.scheme}://{request.url.netloc}"
        f"/vobiz/recording-callback?interaction_id={interaction_id or ''}"
    )
    msg = escape(connect_message or f"Connected to {company_name}. Please start speaking.")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Speak>{msg}</Speak>"
        # recordSession="true" keeps recording alive until hangup (not just until this verb ends).
        # startOnDialAnswer="true" begins capture the moment the outbound leg is answered.
        f'<Record recordSession="true" startOnDialAnswer="true" fileFormat="mp3"'
        f' timeLimit="3600" callbackUrl="{escape(recording_callback)}" callbackMethod="POST" />'
        f'<Stream bidirectional="true" keepCallAlive="true" contentType="audio/x-mulaw;rate=8000">'
        f"{escape(ws_url)}"
        "</Stream>"
        "</Response>"
    )


@router.post("/outgoing-call")
async def outgoing_call(
    request: Request,
    lead_id: int | None = None,
    user_id: int | None = None,
    agent_id: int | None = None,
    session: Session = Depends(get_session),
):
    interaction_id = request.query_params.get("interaction_id")
    call_task_id = request.query_params.get("call_task_id", "0")

    target_user = session.get(User, user_id) if user_id else None
    company = session.get(Company, target_user.company_id) if target_user else None
    company_name = company.name if company else "Rio CRM"
    company_id_val = target_user.company_id if target_user else 0
    connect_msg = _get_connect_message(session, company_id_val, company_name)

    # Check if agent has IVR menu enabled
    if agent_id:
        runtime = session.exec(
            sql_select(VoiceAgentRuntimeConfig).where(VoiceAgentRuntimeConfig.agent_id == agent_id)
        ).first()
        if runtime:
            ivr_menu = (runtime.runtime_json or {}).get("ivr_menu", {})
            if ivr_menu.get("enabled") and ivr_menu.get("options"):
                base_url = f"{request.url.scheme}://{request.url.netloc}"
                ivr_action = (
                    f"{base_url}/ivr-handle"
                    f"?user_id={user_id or 0}&lead_id={lead_id or 0}"
                    f"&interaction_id={interaction_id or ''}&call_task_id={call_task_id}&agent_id={agent_id}"
                )
                response = VoiceResponse()
                greeting = ivr_menu.get("greeting", "Please press a key to continue.")
                timeout = int(ivr_menu.get("timeout_seconds", 5))
                gather = Gather(
                    num_digits=1,
                    action=ivr_action,
                    method="POST",
                    timeout=timeout,
                )
                gather.say(greeting)
                response.append(gather)
                # Fallback if no digit pressed: connect to AI
                ai_response = _build_ai_connect_response(request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name, connect_msg)
                for verb in ai_response.verbs:
                    response.append(verb)
                return HTMLResponse(content=str(response), media_type="application/xml")

    response = _build_ai_connect_response(request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name, connect_msg)
    return HTMLResponse(content=str(response), media_type="application/xml")


@router.post("/ivr-handle")
async def ivr_handle(
    request: Request,
    Digits: str = Form(default=""),
    session: Session = Depends(get_session),
):
    """Handle DTMF digit from Twilio Gather and route accordingly."""
    user_id = request.query_params.get("user_id")
    lead_id = request.query_params.get("lead_id")
    interaction_id = request.query_params.get("interaction_id")
    call_task_id = request.query_params.get("call_task_id", "0")
    agent_id_str = request.query_params.get("agent_id")
    agent_id = int(agent_id_str) if agent_id_str and agent_id_str.isdigit() else None

    target_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    company = session.get(Company, target_user.company_id) if target_user else None
    company_name = company.name if company else "Rio CRM"
    company_id_val = target_user.company_id if target_user else 0
    connect_msg = _get_connect_message(session, company_id_val, company_name)

    # Load IVR menu
    ivr_option = None
    if agent_id:
        runtime = session.exec(
            sql_select(VoiceAgentRuntimeConfig).where(VoiceAgentRuntimeConfig.agent_id == agent_id)
        ).first()
        if runtime:
            ivr_menu = (runtime.runtime_json or {}).get("ivr_menu", {})
            options = ivr_menu.get("options", [])
            ivr_option = next((o for o in options if str(o.get("digit", "")) == str(Digits)), None)

    response = VoiceResponse()

    if not ivr_option:
        ai = _build_ai_connect_response(request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name, connect_msg)
        for verb in ai.verbs:
            response.append(verb)
        return HTMLResponse(content=str(response), media_type="application/xml")

    action = ivr_option.get("action", "agent")

    if action == "transfer":
        transfer_to = ivr_option.get("transfer_to", "")
        if transfer_to:
            response.say(f"Transferring your call. Please hold.")
            dial = Dial()
            dial.number(transfer_to)
            response.append(dial)
        else:
            response.say("Transfer destination not configured.")
            response.hangup()
    elif action == "hangup":
        label = ivr_option.get("label", "")
        if label:
            response.say(f"Thank you. {label}.")
        response.hangup()
    else:
        ai = _build_ai_connect_response(request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name, connect_msg)
        for verb in ai.verbs:
            response.append(verb)

    return HTMLResponse(content=str(response), media_type="application/xml")


@router.post("/plivo-answer")
async def plivo_answer(
    request: Request,
    lead_id: int | None = None,
    user_id: int | None = None,
    agent_id: int | None = None,
    session: Session = Depends(get_session),
):
    """Answer URL for Plivo outbound calls. Returns Plivo XML to bridge to AI pipeline."""
    interaction_id = request.query_params.get("interaction_id")
    call_task_id = request.query_params.get("call_task_id", "0")

    target_user = session.get(User, user_id) if user_id else None
    company = session.get(Company, target_user.company_id) if target_user else None
    company_name = company.name if company else "Rio CRM"
    company_id_val = target_user.company_id if target_user else 0
    connect_msg = _get_connect_message(session, company_id_val, company_name)

    xml = _build_plivo_connect_response(request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name, connect_msg)
    return HTMLResponse(content=xml, media_type="application/xml")


@router.post("/exotel-answer")
async def exotel_answer(
    request: Request,
    lead_id: int | None = None,
    user_id: int | None = None,
    agent_id: int | None = None,
    session: Session = Depends(get_session),
):
    """Answer URL for Exotel outbound calls. Returns ExoML to bridge to AI pipeline."""
    interaction_id = request.query_params.get("interaction_id")
    call_task_id = request.query_params.get("call_task_id", "0")

    ws_url = (
        f"wss://{request.url.netloc}/exotel-media-stream"
        f"?user_id={user_id or 0}&lead_id={lead_id or 0}"
        f"&interaction_id={interaction_id or ''}&call_task_id={call_task_id}&agent_id={agent_id or 0}"
    )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Stream bidirectional="true" url="{escape(ws_url)}"/>'
        "</Response>"
    )
    return HTMLResponse(content=xml, media_type="application/xml")


@router.post("/exotel/status-callback")
async def exotel_status_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """Handle Exotel call status updates."""
    try:
        form = await request.form()
        payload = {k: str(v) for k, v in form.items()}
    except Exception:
        payload = {}

    # Exotel sends Status field
    raw_status = (payload.get("Status") or payload.get("status") or "").lower()
    call_sid = payload.get("CallSid") or payload.get("call_sid") or ""
    interaction_id = request.query_params.get("interaction_id")
    user_id = request.query_params.get("user_id")
    call_task_id = request.query_params.get("call_task_id")

    _status_map = {
        "in-progress": "in_progress",
        "no-answer": "no_answer",
        "no_answer": "no_answer",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "busy": "busy",
        "failed": "failed",
        "completed": "completed",
    }
    provider_status = _status_map.get(raw_status, raw_status or "initiated")

    actor_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    db_interaction = session.get(Interaction, int(interaction_id)) if interaction_id and interaction_id.isdigit() else None

    recording_url = payload.get("RecordingUrl") or payload.get("recording_url") or ""

    if db_interaction:
        db_interaction.metadata_json = {
            **(db_interaction.metadata_json or {}),
            "call_sid": call_sid,
            "provider_call_status": provider_status,
            "exotel_payload": payload,
        }
        _TERMINAL = {"completed", "busy", "no_answer", "failed", "cancelled", "error"}
        if provider_status in _TERMINAL:
            db_interaction.status = "ended"
            db_interaction.ended_at = db_interaction.ended_at or utc_now()
        if recording_url and not db_interaction.recording_url:
            db_interaction.recording_url = recording_url
        db_interaction.updated_at = utc_now()
        if actor_user:
            db_interaction.updated_by = actor_user.id
        session.add(db_interaction)
        session.commit()

    _TERMINAL_OUTCOME = {"completed", "busy", "no_answer", "failed", "cancelled"}
    if provider_status in _TERMINAL_OUTCOME and actor_user and call_task_id and call_task_id.isdigit() and int(call_task_id) != 0:
        try:
            from services.call.outcome_service import apply_call_outcome
            transcript = db_interaction.transcript if db_interaction else None
            apply_call_outcome(
                session=session,
                company_id=actor_user.company_id,
                actor_user_id=actor_user.id,
                task_id=int(call_task_id),
                interaction_id=int(interaction_id) if interaction_id and interaction_id.isdigit() else None,
                raw_status=provider_status,
                transcript=transcript,
            )
        except Exception as exc:
            logger.warning("[Exotel] status-callback outcome error: %s", exc)

    return {"status": "tracked", "call_status": provider_status}


@router.post("/vobiz-answer")
async def vobiz_answer(
    request: Request,
    lead_id: int | None = None,
    user_id: int | None = None,
    agent_id: int | None = None,
    session: Session = Depends(get_session),
):
    """Answer URL for Vobiz outbound calls. Returns Vobiz XML to bridge to AI pipeline."""
    interaction_id = request.query_params.get("interaction_id")
    call_task_id = request.query_params.get("call_task_id", "0")

    target_user = session.get(User, user_id) if user_id else None
    company = session.get(Company, target_user.company_id) if target_user else None
    company_name = company.name if company else "Rio CRM"
    company_id_val = target_user.company_id if target_user else 0
    connect_msg = _get_connect_message(session, company_id_val, company_name)

    vxml = _build_vobiz_connect_response(request, user_id, lead_id, interaction_id, call_task_id, agent_id, company_name, connect_msg)
    return HTMLResponse(content=vxml, media_type="application/xml")


# All statuses that indicate a call has ended (terminal) — used across providers
_VOBIZ_TERMINAL = {
    "completed", "busy", "no_answer", "no-answer", "failed",
    "cancelled", "canceled", "error", "low_balance", "stopped",
}

@router.post("/vobiz/status-callback")
async def vobiz_status_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    form = await request.form()
    payload = {key: str(value) for key, value in form.items()}
    event = (payload.get("Event") or payload.get("event") or "").lower()
    interaction_id = request.query_params.get("interaction_id")
    user_id = request.query_params.get("user_id")

    status_map = {
        "ring": "ringing",
        "answer": "in_progress",
        "hangup": "completed",
        "completed": "completed",
        "failed": "failed",
        "busy": "busy",
        "noanswer": "no_answer",
        "no-answer": "no_answer",
        "no_answer": "no_answer",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "error": "error",
        "low_balance": "low_balance",
        "stopped": "stopped",
    }
    provider_status = status_map.get(event, event or "initiated")

    actor_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    interaction = session.get(Interaction, int(interaction_id)) if interaction_id and interaction_id.isdigit() else None
    if interaction:
        # Extract all relevant fields from payload BEFORE any session op to avoid lazy-load races.
        call_uuid_from_payload = (
            payload.get("CallUuid") or payload.get("call_uuid") or payload.get("uuid")
        )
        # Vobiz sends recording URL in the status callback on terminal events (same as Twilio).
        recording_url_from_payload = (
            payload.get("RecordUrl") or payload.get("record_url")
            or payload.get("RecordFile") or payload.get("recording_url")
            or payload.get("RecordingUrl")
        )
        recording_duration_from_payload = (
            payload.get("RecordingDuration") or payload.get("recording_duration")
        )
        existing_meta = dict(interaction.metadata_json or {})
        new_meta = {
            **existing_meta,
            "provider_call_status": provider_status,
            "provider_status": provider_status,
            "vobiz_event": payload.get("Event") or payload.get("event"),
            "vobiz_payload": payload,
        }
        if call_uuid_from_payload:
            new_meta["call_uuid"] = call_uuid_from_payload
        interaction.metadata_json = new_meta
        if provider_status in _VOBIZ_TERMINAL:
            interaction.status = "ended"
            interaction.ended_at = interaction.ended_at or utc_now()
        # Save recording URL if Vobiz included it in this status event.
        if recording_url_from_payload and not interaction.recording_url:
            interaction.recording_url = recording_url_from_payload
            if recording_duration_from_payload:
                try:
                    interaction.recording_duration = int(float(recording_duration_from_payload))
                except (ValueError, TypeError):
                    pass
            logger.info(
                "[Vobiz] Recording URL saved from status callback: interaction=%s url=%s",
                interaction_id, recording_url_from_payload,
            )
        interaction.updated_at = utc_now()
        if actor_user:
            interaction.updated_by = actor_user.id
        session.add(interaction)
        session.commit()

        # Recording is handled via <Record recordSession="true" /> in the answer XML —
        # no REST trigger needed. The recording callback delivers the URL when the call ends.

    return {"status": "tracked", "call_status": provider_status}


@router.post("/make-call")
async def make_call(
    to: str,
    lead_id: Optional[int] = None,
    call_task_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    current_user: User = Depends(PermissionChecker("call_task.manage")),
    session: Session = Depends(get_session),
):
    return initiate_outbound_call(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        to=to,
        lead_id=lead_id,
        call_task_id=call_task_id,
        agent_id=agent_id,
    )


@router.post("/send-sms")
async def send_sms(
    to: str,
    message: str,
    current_user: User = Depends(PermissionChecker("call_task.manage")),
    session: Session = Depends(get_session),
):
    account_sid = get_company_credential(session, current_user.company_id, "TWILIO_ACCOUNT_SID")
    auth_token = get_company_credential(session, current_user.company_id, "TWILIO_AUTH_TOKEN")
    from_number = (
        get_company_credential(session, current_user.company_id, "TWILIO_PHONE_NUMBER")
        or os.getenv("PHONE_NUMBER_FROM")
    )

    if not all([account_sid, auth_token, from_number]):
        raise HTTPException(status_code=400, detail="Twilio credentials are not configured")

    client = TwilioClient(account_sid, auth_token)
    sms = client.messages.create(
        to=normalize_phone(to),
        from_=from_number,
        body=message,
    )
    return {"status": "sent", "message_sid": sms.sid}


@router.post("/incoming-sms")
async def incoming_sms():
    response = MessagingResponse()
    response.message("Thanks. Your message has been received.")
    return HTMLResponse(content=str(response), media_type="application/xml")


@router.post("/twilio/status-callback")
async def twilio_status_callback(
    request: Request,
    CallStatus: str = Form(...),
    CallSid: str = Form(...),
    session: Session = Depends(get_session),
):
    """Handle Twilio call status updates. 
    Synchronous for UI updates (ringing/status), async via AgentTask for heavy outcome processing.
    """
    # form = await request.form()
    # payload = {key: value for key, value in form.items()}
    
    call_task_id = request.query_params.get("call_task_id")
    interaction_id = request.query_params.get("interaction_id")
    user_id = request.query_params.get("user_id")

    # Normalize Twilio's hyphenated values to underscores for consistency.
    # Twilio sends "in-progress", "no-answer", "canceled" — we store "in_progress", "no_answer", "cancelled".
    _twilio_norm = {
        "in-progress": "in_progress",
        "no-answer": "no_answer",
        "canceled": "cancelled",
    }
    CallStatus = _twilio_norm.get(CallStatus, CallStatus)

    # Always persist status on the interaction — needed for real-time polling by frontend.
    actor_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    db_interaction = None
    company_id = None
    if interaction_id and interaction_id.isdigit():
        db_interaction = session.get(Interaction, int(interaction_id))
        if db_interaction:
            company_id = db_interaction.company_id
            db_interaction.metadata_json = {
                **(db_interaction.metadata_json or {}),
                "call_sid": CallSid,
                "provider_call_status": CallStatus,
            }
            db_interaction.updated_at = utc_now()
            if actor_user:
                db_interaction.updated_by = actor_user.id
            session.add(db_interaction)
            session.commit()

    # 1. ALWAYS persist status on interaction synchronously — needed for real-time polling.
    # actor_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    # db_interaction = None
    # company_id = None

    # if interaction_id and interaction_id.isdigit():
    #     db_interaction = session.get(Interaction, int(interaction_id))
    #     if db_interaction:
    #         company_id = db_interaction.company_id
    #         db_interaction.metadata_json = {
    #             **(db_interaction.metadata_json or {}),
    #             "call_sid": CallSid,
    #             "provider_call_status": CallStatus,
    #         }
    #         db_interaction.updated_at = utc_now()
    #         if actor_user:
    #             db_interaction.updated_by = actor_user.id
    #         session.add(db_interaction)
    #         session.commit()

    if not company_id and actor_user:
        company_id = actor_user.company_id

    # Call monitor: publish lifecycle events.
    # "connected" and "ended" (answered) are published by run_media_stream.
    # "ringing" and unanswered terminal events are published here.
    _UNANSWERED = {"busy", "no_answer", "failed", "cancelled", "error", "low_balance", "stopped"}
    if call_task_id and call_task_id.isdigit() and int(call_task_id) != 0:
        if CallStatus in {"ringing", "initiated", "in_progress", "queued"} or CallStatus in _UNANSWERED:
            try:
                from services import call_status_broadcaster
                _task = session.get(CallTask, int(call_task_id))
                if _task:
                    _lead = session.get(Lead, _task.lead_id) if _task.lead_id else None
                    if CallStatus in _UNANSWERED:
                        _monitor_status = "ended"
                        _monitor_outcome = CallStatus
                    elif CallStatus == "in_progress":
                        _monitor_status = "connected"
                        _monitor_outcome = None
                    else:
                        _monitor_status = CallStatus  # "ringing" | "initiated" | "queued"
                        _monitor_outcome = None
                    call_status_broadcaster.publish(
                        company_id=_task.company_id,
                        campaign_id=_task.campaign_id,
                        call_task_id=_task.id,
                        interaction_id=interaction_id,
                        lead_id=_task.lead_id,
                        lead_name=_lead.name if _lead else None,
                        status=_monitor_status,
                        outcome=_monitor_outcome,
                    )
            except Exception:
                pass

    # Outcome processing only for terminal state
    TERMINAL = {"completed", "busy", "no_answer", "failed", "cancelled", "error", "low_balance", "stopped"}
    if CallStatus not in TERMINAL:
        return {"status": "tracked", "call_status": CallStatus}

    # Defensive: mark interaction as ended for any terminal state, regardless
    # of whether actor_user is resolved or apply_call_outcome later raises.
    # Previously, a webhook with no actor_user OR a partial outcome failure
    # left the interaction permanently 'active'.  Idempotent — last-write
    # wins; downstream apply_call_outcome may set additional fields but
    # 'ended' status is what unblocks UI + cleanup tasks.
    if db_interaction and db_interaction.status != "ended":
        db_interaction.status = "ended"
        db_interaction.ended_at = utc_now()
        db_interaction.updated_at = utc_now()
        session.add(db_interaction)
        session.commit()

    if not actor_user:
        return {"status": "tracked", "call_status": CallStatus}
    
    transcript = db_interaction.transcript if db_interaction else None
    interaction_id_int = int(interaction_id) if interaction_id and interaction_id.isdigit() else None
    has_call_task = bool(call_task_id and call_task_id.isdigit() and int(call_task_id) != 0)

    if has_call_task:
        result = apply_call_outcome(
            session=session,
            company_id=actor_user.company_id,
            actor_user_id=actor_user.id,
            task_id=int(call_task_id),
            interaction_id=interaction_id_int,
            raw_status=CallStatus,
            transcript=transcript,
        )
        return {"status": "processed", "result": result}

    # Manual 'Call now' path — no CallTask. Advance lead from interaction.lead_id.
    lead_id_from_interaction = db_interaction.lead_id if db_interaction else None
    if not lead_id_from_interaction:
        return {"status": "tracked", "call_status": CallStatus}
    
    result = apply_lead_only_outcome(
        session=session,
        company_id=actor_user.company_id,
        actor_user_id=actor_user.id,
        lead_id=lead_id_from_interaction,
        interaction_id=interaction_id_int,
        raw_status=CallStatus,
        transcript=transcript,
    )
    return {"status": "processed_lead_only", "result": result}

    # 2. Synchronous Real-time Broadcast (Ringing / Ended)
    # _UNANSWERED = {"busy", "no-answer", "failed", "canceled"}
    # if call_task_id and call_task_id.isdigit() and int(call_task_id) != 0 and company_id:
    #     if CallStatus == "ringing" or CallStatus in _UNANSWERED:
    #         try:
    #             from services.call import call_status_broadcaster
    #             _task = session.get(CallTask, int(call_task_id))
    #             if _task:
    #                 _lead = session.get(Lead, _task.lead_id) if _task.lead_id else None
    #                 _monitor_status = "ringing" if CallStatus == "ringing" else "ended"
    #                 _monitor_outcome = CallStatus.replace("-", "_") if CallStatus in _UNANSWERED else None
    #                 call_status_broadcaster.publish(
    #                     company_id=_task.company_id,
    #                     campaign_id=_task.campaign_id,
    #                     call_task_id=_task.id,
    #                     interaction_id=interaction_id,
    #                     lead_id=_task.lead_id,
    #                     lead_name=_lead.name if _lead else None,
    #                     status=_monitor_status,
    #                     outcome=_monitor_outcome,
    #                 )
    #         except Exception as exc:
    #             logger.warning("[Telephony] Real-time broadcast failed: %s", exc)

    # 3. Queue heavy outcome processing for terminal states only
    # TERMINAL = {"completed", "busy", "no-answer", "failed", "canceled"}
    # if CallStatus in TERMINAL and company_id:
    #     from services.agent.agent_task_service import create_agent_task
    #     create_agent_task(
    #         session=session,
    #         company_id=company_id,
    #         task_type="process_call_status",
    #         assigned_agent="webhook_handlers",
    #         input_json={
    #             "payload": payload,
    #             "query_params": {
    #                 "call_task_id": call_task_id,
    #                 "interaction_id": interaction_id,
    #                 "user_id": user_id,
    #             }
    #         },
    #         idempotency_key=f"call_status:{CallSid}:{CallStatus}",
    #         requires_approval=False,
    #     )

    # return {"status": "queued" if CallStatus in TERMINAL else "tracked"}


@router.get("/call-status")
async def get_call_status(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Poll endpoint for real-time call status. Returns provider_call_status from metadata."""
    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")

    metadata = interaction.metadata_json or {}
    raw = metadata.get("provider_call_status", "initiated")
    TERMINAL = {
        "completed", "busy",
        "no-answer", "no_answer",      # both formats
        "failed",
        "canceled", "cancelled",       # both spellings
        "error", "low_balance", "stopped",
    }
    return {
        "interaction_id": interaction_id,
        "call_status": raw,
        "is_terminal": raw in TERMINAL,
    }


@router.post("/twilio/recording-callback")
async def twilio_recording_callback(
    request: Request,
    RecordingUrl: str = Form(...),
    RecordingDuration: Optional[str] = Form(None),
    RecordingSid: str = Form(...),
    session: Session = Depends(get_session),
):
    """Receive Twilio recording URL and persist it on the interaction."""
    interaction_id = request.query_params.get("interaction_id")
    if not interaction_id or not interaction_id.isdigit():
        return {"status": "ignored"}

    interaction = session.get(Interaction, int(interaction_id))
    if not interaction:
        return {"status": "not_found"}

    # Twilio recording URL — append .mp3 for direct playback
    audio_url = RecordingUrl if RecordingUrl.endswith(".mp3") else f"{RecordingUrl}.mp3"
    interaction.recording_url = audio_url
    if RecordingDuration and RecordingDuration.isdigit():
        interaction.recording_duration = int(RecordingDuration)
    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "recording_sid": RecordingSid,
    }
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()
    return {"status": "saved", "interaction_id": interaction_id}


_VOBIZ_RECORDING_URL_FIELDS = ("RecordFile", "RecordUrl", "recording_url", "record_url", "url", "RecordingUrl")
_VOBIZ_RECORDING_DUR_FIELDS = ("RecordingDuration", "recording_duration", "duration_ms", "duration")
_VOBIZ_RECORDING_SID_FIELDS = ("RecordingID", "recording_id", "RecordingId", "id")


@router.post("/vobiz/recording-callback")
async def vobiz_recording_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """Receive Vobiz recording URL and persist it on the interaction."""
    interaction_id = request.query_params.get("interaction_id")
    if not interaction_id or not interaction_id.isdigit():
        return {"status": "ignored"}

    interaction = session.get(Interaction, int(interaction_id))
    if not interaction:
        return {"status": "not_found"}

    # Parse body — try form first, then JSON (body can only be read once in Starlette).
    data: dict = {}
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            data = {k: str(v) for k, v in form.items()}
        except Exception:
            pass

    recording_url = next((data.get(f) for f in _VOBIZ_RECORDING_URL_FIELDS if data.get(f)), None)
    recording_duration_raw = next((data.get(f) for f in _VOBIZ_RECORDING_DUR_FIELDS if data.get(f)), None)
    recording_sid = next((data.get(f) for f in _VOBIZ_RECORDING_SID_FIELDS if data.get(f)), None)

    logger.info(
        "[Vobiz] recording-callback interaction=%s url=%s raw_data_keys=%s",
        interaction_id, recording_url, list(data.keys()),
    )

    if not recording_url:
        return {"status": "ignored_no_url", "interaction_id": interaction_id, "received_keys": list(data.keys())}

    interaction.recording_url = recording_url
    if recording_duration_raw:
        try:
            dur = float(recording_duration_raw)
            interaction.recording_duration = int(dur / 1000 if dur > 3600 else dur)
        except (ValueError, TypeError):
            pass
    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "recording_sid": recording_sid or "",
    }
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()
    return {"status": "saved", "interaction_id": interaction_id}


@router.post("/exotel/recording-callback")
async def exotel_recording_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """Receive Exotel recording URL and persist it on the interaction."""
    interaction_id = request.query_params.get("interaction_id")
    if not interaction_id or not interaction_id.isdigit():
        return {"status": "ignored"}

    interaction = session.get(Interaction, int(interaction_id))
    if not interaction:
        return {"status": "not_found"}

    # Exotel sends form data; also accept JSON body fallback
    recording_url = recording_duration = recording_sid = None
    try:
        form = await request.form()
        payload = {k: str(v) for k, v in form.items()}
        recording_url = payload.get("RecordingUrl") or payload.get("recording_url")
        recording_duration = payload.get("RecordingDuration") or payload.get("recording_duration")
        recording_sid = payload.get("RecordingSid") or payload.get("recording_sid")
    except Exception:
        pass

    if not recording_url:
        try:
            body = await request.json()
            recording_url = body.get("RecordingUrl") or body.get("recording_url")
            recording_duration = recording_duration or body.get("RecordingDuration")
            recording_sid = recording_sid or body.get("RecordingSid")
        except Exception:
            pass

    if not recording_url:
        return {"status": "ignored_not_ready"}

    if not interaction.recording_url:
        interaction.recording_url = recording_url
    if recording_duration:
        try:
            interaction.recording_duration = int(float(recording_duration))
        except (ValueError, TypeError):
            pass
    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "recording_sid": recording_sid or "",
    }
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()
    return {"status": "saved", "interaction_id": interaction_id}


@router.post("/enablex/event")
async def enablex_event_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """Handle EnableX call lifecycle events (ringing / answer / disconnected)."""
    try:
        payload = await request.json()
    except Exception:
        try:
            form = await request.form()
            payload = {k: str(v) for k, v in form.items()}
        except Exception:
            payload = {}

    voice_id = payload.get("voice_id") or payload.get("call_id") or ""
    event = (payload.get("status") or payload.get("event") or "").lower()
    interaction_id = request.query_params.get("interaction_id")
    user_id = request.query_params.get("user_id")
    call_task_id = request.query_params.get("call_task_id")

    _status_map = {
        "ringing": "ringing",
        "ring": "ringing",
        "answer": "in_progress",
        "answered": "in_progress",
        "connected": "in_progress",
        "in_progress": "in_progress",
        "disconnected": "completed",
        "completed": "completed",
        "failed": "failed",
        "busy": "busy",
        "no-answer": "no_answer",
        "no_answer": "no_answer",
        "noanswer": "no_answer",
        "cancelled": "cancelled",
        "canceled": "cancelled",
    }
    provider_status = _status_map.get(event, event or "initiated")

    _TERMINAL = {"completed", "disconnected", "failed", "busy", "no_answer", "cancelled", "error"}

    actor_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    interaction = session.get(Interaction, int(interaction_id)) if interaction_id and interaction_id.isdigit() else None

    if interaction:
        interaction.metadata_json = {
            **(interaction.metadata_json or {}),
            "provider_call_status": provider_status,
            "provider_status": provider_status,
            "enablex_event": event,
            "enablex_payload": payload,
        }
        if voice_id:
            interaction.metadata_json["call_sid"] = interaction.metadata_json.get("call_sid") or voice_id
        if provider_status in _TERMINAL:
            interaction.status = "ended"
            interaction.ended_at = interaction.ended_at or utc_now()
        interaction.updated_at = utc_now()
        if actor_user:
            interaction.updated_by = actor_user.id
        session.add(interaction)
        session.commit()

        # Trigger recording the moment callee answers
        if event in ("answer", "answered", "connected") and not interaction.recording_url:
            resolved_voice_id = (
                voice_id
                or (interaction.metadata_json or {}).get("call_sid")
                or ""
            )
            if resolved_voice_id:
                from services.campaign.dialer_service import _resolve_callback_base
                callback_base = _resolve_callback_base(session, interaction.company_id)
                _trigger_enablex_recording(session, interaction.company_id, interaction.id, resolved_voice_id, callback_base)

    if provider_status in _TERMINAL and actor_user and call_task_id and call_task_id.isdigit() and int(call_task_id) != 0:
        try:
            transcript = interaction.transcript if interaction else None
            apply_call_outcome(
                session=session,
                company_id=actor_user.company_id,
                actor_user_id=actor_user.id,
                task_id=int(call_task_id),
                interaction_id=int(interaction_id) if interaction_id and interaction_id.isdigit() else None,
                raw_status=provider_status,
                transcript=transcript,
            )
        except Exception as exc:
            logger.warning("[EnableX] event-callback outcome error: %s", exc)

    return {"status": "tracked", "call_status": provider_status}


@router.post("/enablex/recording-callback")
async def enablex_recording_callback(
    request: Request,
    session: Session = Depends(get_session),
):
    """Receive EnableX recording URL and persist it on the interaction."""
    interaction_id = request.query_params.get("interaction_id")
    if not interaction_id or not interaction_id.isdigit():
        return {"status": "ignored"}

    interaction = session.get(Interaction, int(interaction_id))
    if not interaction:
        return {"status": "not_found"}

    recording_url = recording_duration = recording_sid = None
    try:
        body = await request.json()
        recording_url = (
            body.get("recording_url") or body.get("RecordingUrl")
            or body.get("url") or ""
        )
        recording_duration = body.get("duration") or body.get("RecordingDuration")
        recording_sid = body.get("recording_id") or body.get("RecordingSid")
    except Exception:
        pass

    if not recording_url:
        try:
            form = await request.form()
            payload = {k: str(v) for k, v in form.items()}
            recording_url = payload.get("recording_url") or payload.get("RecordingUrl") or ""
            recording_duration = recording_duration or payload.get("duration") or payload.get("RecordingDuration")
            recording_sid = recording_sid or payload.get("recording_id") or payload.get("RecordingSid")
        except Exception:
            pass

    if not recording_url:
        return {"status": "ignored_not_ready"}

    if not interaction.recording_url:
        interaction.recording_url = recording_url
    if recording_duration:
        try:
            interaction.recording_duration = int(float(recording_duration))
        except (ValueError, TypeError):
            pass
    interaction.metadata_json = {
        **(interaction.metadata_json or {}),
        "recording_sid": recording_sid or "",
    }
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()
    return {"status": "saved", "interaction_id": interaction_id}


@router.post("/warm-transfer")
async def warm_transfer(
    interaction_id: int,
    transfer_to: str,
    isr_name: Optional[str] = None,
    current_user: User = Depends(PermissionChecker("call_task.manage")),
    session: Session = Depends(get_session),
):
    """
    Bridge an active AI call to a human ISR in real-time.
    Supports Twilio (Conference), Exotel (Transfer API), and EnableX (dial-out).
    """
    return execute_warm_transfer(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        interaction_id=interaction_id,
        transfer_to=transfer_to,
        isr_name=isr_name,
    )


@router.api_route("/warm-transfer-instructions", methods=["GET", "POST"])
async def warm_transfer_instructions(transfer_to: str):
    """Provider callback XML used by Plivo and Vobiz for an active transfer."""
    from xml.sax.saxutils import escape as xml_escape

    destination = xml_escape(transfer_to)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Speak>Please hold while we connect you to a human agent.</Speak>"
        f"<Dial><Number>{destination}</Number></Dial></Response>"
    )
    return HTMLResponse(content=xml, media_type="application/xml")


@router.post("/outbound/callback")
async def outbound_callback(
    task_id: int,
    raw_status: str,
    interaction_id: int | None = None,
    transcript: str | None = None,
    confidence: float | None = None,
    actor_user_id: int | None = None,
    session: Session = Depends(get_session),
):
    """Generic callback for outbound providers to report call outcome."""
    if actor_user_id is None:
        raise HTTPException(status_code=400, detail="actor_user_id is required")

    user = session.get(User, actor_user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Actor user not found")

    result = apply_call_outcome(
        session=session,
        company_id=user.company_id,
        actor_user_id=user.id,
        task_id=task_id,
        interaction_id=interaction_id,
        raw_status=raw_status,
        transcript=transcript,
        confidence=Decimal(str(confidence)) if confidence is not None else None,
    )

    return {"status": "processed", "result": result}


# ---------------------------------------------------------------------------
# Rio webhook — receives call-end payload and stores full data in Interaction
# ---------------------------------------------------------------------------

@router.post("/rio/webhook")
async def rio_call_webhook(
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Receive Rio call-end webhook and store full payload in Interaction.metadata_json.

    Matching priority:
    1. payload.metadata.interaction_id  → direct Interaction ID match
    2. payload.to_number               → Lead.normalized_phone → most recent Interaction (last 2 h)
    """
    from datetime import timedelta

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    execution_id = payload.get("id") or payload.get("execution_id") or payload.get("session_id")
    rio_agent_id = payload.get("agent_id")
    to_number = payload.get("to_number") or payload.get("to")
    from_number = payload.get("from_number") or payload.get("from")
    metadata = payload.get("metadata") or {}

    logger.info(
        "[Rio] Webhook received — execution_id=%s agent=%s to=%s from=%s",
        execution_id, rio_agent_id, to_number, from_number,
    )

    interaction: Interaction | None = None

    # Strategy 1: explicit interaction_id in Rio metadata
    explicit_id = metadata.get("interaction_id") or metadata.get("rio_interaction_id")
    if explicit_id:
        try:
            interaction = session.get(Interaction, int(explicit_id))
        except (ValueError, TypeError):
            pass

    # Strategy 2: match by called phone number — most recent interaction in last 2 hours
    if interaction is None and to_number:
        normalized = normalize_phone(to_number)
        lead = session.exec(
            select(Lead).where(Lead.normalized_phone == normalized)
        ).first()
        if lead:
            cutoff = utc_now() - timedelta(hours=2)
            interaction = session.exec(
                select(Interaction)
                .where(
                    Interaction.lead_id == lead.id,
                    Interaction.started_at >= cutoff,
                )
                .order_by(Interaction.started_at.desc())
            ).first()

    if interaction is None:
        logger.warning(
            "[Rio] No matching Interaction found for execution_id=%s to=%s",
            execution_id, to_number,
        )
        return {"status": "no_match", "execution_id": execution_id}

    # Merge full payload into metadata_json (preserve existing keys, add rio data)
    existing_meta = dict(interaction.metadata_json or {})
    existing_meta["rio"] = {
        "execution_id": execution_id,
        "agent_id": rio_agent_id,
        "call_status": payload.get("call_status"),
        "usage_breakdown": payload.get("usage_breakdown"),
        "cost_breakdown": payload.get("cost_breakdown"),
        "latency_data": payload.get("latency_data"),
        "tool_call_logs": payload.get("tool_call_logs"),
        "extracted_data": payload.get("extracted_data"),
        "telephony_data": payload.get("telephony_data"),
        "to_number": to_number,
        "from_number": from_number,
        "duration": payload.get("duration") or (
            (payload.get("telephony_data") or {}).get("duration")
        ),
        "received_at": utc_now().isoformat(),
    }
    interaction.metadata_json = existing_meta

    # Update duration if we got a better value from Rio
    rio_duration = existing_meta["rio"].get("duration")
    if rio_duration and not interaction.recording_duration:
        try:
            interaction.recording_duration = int(float(rio_duration))
        except (ValueError, TypeError):
            pass

    session.add(interaction)
    session.commit()

    logger.info(
        "[Rio] Stored full payload → Interaction #%s (execution_id=%s)",
        interaction.id, execution_id,
    )
    return {"status": "stored", "interaction_id": interaction.id, "execution_id": execution_id}

