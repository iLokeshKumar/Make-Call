import logging
import os
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select
from twilio.rest import Client as TwilioClient
from twilio.twiml.messaging_response import MessagingResponse
from twilio.twiml.voice_response import Connect, VoiceResponse

from auth import PermissionChecker, get_current_user
from communicators import ExotelCommunicator, TwilioCommunicator
from credentials_service import get_company_credential
from database import get_session
from models.models import CallTask, Company, Interaction, Lead, User, utc_now
from services.campaign.dialer_service import initiate_outbound_call
from services.call.outcome_service import apply_call_outcome
from services.call.outbound_call_service import start_call_task
from services.call.warm_transfer_service import execute_warm_transfer
from utils.phone import normalize_phone
from utils.url_utils import normalize_base_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Telephony"])


def get_communicator_for_source(source: str, websocket):
    if source == "exotel":
        return ExotelCommunicator(websocket)
    return TwilioCommunicator(websocket)


@router.post("/outgoing-call")
async def outgoing_call(
    request: Request,
    lead_id: int | None = None,
    user_id: int | None = None,
    session: Session = Depends(get_session),
):
    interaction_id = request.query_params.get("interaction_id")
    call_task_id = request.query_params.get("call_task_id", "0")

    target_user = session.get(User, user_id) if user_id else None
    company = session.get(Company, target_user.company_id) if target_user else None
    company_name = company.name if company else "Rio CRM"

    response = VoiceResponse()
    response.say(f"Connected to {company_name}. Please start speaking.")
    connect = Connect()
    connect.stream(
        url=(
            f"wss://{request.url.netloc}/media-stream"
            f"?user_id={user_id or 0}&lead_id={lead_id or 0}&interaction_id={interaction_id or ''}&call_task_id={call_task_id}"
        )
    )
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")


@router.post("/make-call")
async def make_call(
    to: str,
    lead_id: Optional[int] = None,
    call_task_id: Optional[int] = None,
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
    call_task_id = request.query_params.get("call_task_id")
    interaction_id = request.query_params.get("interaction_id")
    user_id = request.query_params.get("user_id")

    # Always persist status on the interaction — needed for real-time polling by frontend.
    actor_user = session.get(User, int(user_id)) if user_id and user_id.isdigit() else None
    db_interaction = None
    if interaction_id and interaction_id.isdigit():
        db_interaction = session.get(Interaction, int(interaction_id))
        if db_interaction:
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

    # Call monitor: publish "ringing" and "ended" (unanswered) events. "connected" and "ended" (answered) are published by run_media_stream. "completed" terminal state is also handled by run_media_stream, so skip it here.
    _UNANSWERED = {"busy", "no-answer", "failed", "canceled"}
    if call_task_id and call_task_id.isdigit() and int(call_task_id) != 0:
        if CallStatus == "ringing" or CallStatus in _UNANSWERED:
            try:
                from services import call_status_broadcaster
                _task = session.get(CallTask, int(call_task_id))
                if _task:
                    _lead = session.get(Lead, _task.lead_id) if _task.lead_id else None
                    _monitor_status = "ringing" if CallStatus == "ringing" else "ended"
                    _monitor_outcome = CallStatus.replace("-", "_") if CallStatus in _UNANSWERED else None
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

    # Outcome processing only for terminal state with a valid call task
    TERMINAL = {"completed", "busy", "no-answer", "failed", "canceled"}
    if CallStatus not in TERMINAL:
        return {"status": "tracked", "call_status": CallStatus}
    if not call_task_id or not call_task_id.isdigit() or int(call_task_id) == 0:
        return {"status": "tracked", "call_status": CallStatus}
    if not actor_user:
        return {"status": "tracked", "call_status": CallStatus}

    transcript = db_interaction.transcript if db_interaction else None
    result = apply_call_outcome(
        session=session,
        company_id=actor_user.company_id,
        actor_user_id=actor_user.id,
        task_id=int(call_task_id),
        interaction_id=int(interaction_id) if interaction_id and interaction_id.isdigit() else None,
        raw_status=CallStatus,
        transcript=transcript,
    )
    return {"status": "processed", "result": result}


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
    TERMINAL = {"completed", "busy", "no-answer", "failed", "canceled"}
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

