import logging
import base64
import json
import asyncio
import aiohttp
import requests
import io
import pandas as pd
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from sqlmodel import Session, select
from twilio.twiml.voice_response import VoiceResponse, Connect, Say
from twilio.twiml.messaging_response import MessagingResponse

from database import get_session, engine
from models.models import Lead, Interaction, SystemSettings, Product, ApolloSearch, User
import os
from utils.config import DOMAIN
from credentials_service import get_credential
from utils.phone import normalize_phone
from utils.lead_utils import get_comprehensive_lead_context
from auth import RoleChecker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Telephony"])

@router.post("/outgoing-call")
async def outgoing_call(request: Request, lead_id: int = None):
    """Returns TwiML to connect the call to the WebSocket stream."""
    response = VoiceResponse()

    # Create an interaction record
    with Session(engine) as session:
        # Get lead phone for better labeling
        lead_phone = ""
        if lead_id and lead_id > 0:
            lead = session.get(Lead, lead_id)
            if lead:
                lead_phone = lead.phone
        
        content = f"Outbound to Lead #{lead_id}" if lead_id and lead_id > 0 else "Outbound Call"
        
        interaction = Interaction(
            lead_id=lead_id if lead_id else 0,
            type="call",
            content=content,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction)
        
        engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
        active_engine = (engine_setting.value if engine_setting else "gemini").strip().lower()

        admin = session.exec(select(User).where(User.role == "admin")).first()
        company_name = admin.company_name if admin and admin.company_name else "Yexis Electronics"

    if active_engine == "mistral":
        response.say(f"Connected to Digital Sales Representative from {company_name} by Mistral. Please start speaking.")
    elif active_engine == "gemini":
        response.say(f"Connected to Digital Sales Representative from {company_name} by Google. Please start speaking.")
    else:
        response.say(f"Connected to {company_name} Digital Sales Representative. Please start speaking.")
    
    connect = Connect()
    stream = connect.stream(url=f'wss://{request.url.netloc}/media-stream')
    stream.parameter(name="interaction_id", value=str(interaction.id))
    stream.parameter(name="lead_id", value=str(lead_id or 0))
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@router.post("/make-call")
async def make_call(to: str, lead_id: Optional[int] = None, engine_type: str = "mistral-cartesia", interaction_id: Optional[str] = None, current_user: User = Depends(RoleChecker(["admin", "user"]))):
    """Initiates an outbound call via selected telephony engine."""
    from utils.encryption import decrypt_value
    from twilio.rest import Client as TwilioClient
    
    try:
        # Standardize number (Handle Indian numbers specifically)
        clean_number = "".join(filter(str.isdigit, to))
        
        if to.startswith("+"):
            pass
        elif len(clean_number) == 10:
            # Standard 10-digit Indian number
            to = f"+91{clean_number}"
        elif len(clean_number) == 12 and clean_number.startswith("91"):
            # Already includes 91, just add +
            to = f"+{clean_number}"
        else:
            # Fallback for other formats
            to = f"+{clean_number}" if not to.startswith("+") else to
            
        with Session(engine) as session:
            # Unified Credential Retrieval (Priority: User DB -> Global DB -> .env)
            sid = get_credential("TWILIO_ACCOUNT_SID", user_id=current_user.id) or os.getenv("TWILIO_ACCOUNT_SID")
            token = get_credential("TWILIO_AUTH_TOKEN", user_id=current_user.id) or os.getenv("TWILIO_AUTH_TOKEN")
            from_number = get_credential("PHONE_NUMBER_FROM", user_id=current_user.id) or os.getenv("PHONE_NUMBER_FROM")

            logger.info(f"📞 [telephony] Attempting call for user {current_user.username} (ID: {current_user.id})")
            logger.info(f"🔑 [telephony] Using SID: {sid[:6]}...{sid[-4:] if sid else 'NONE'}")
            
            # Additional keys for other providers in case needed
            exotel_sid = get_credential("EXOTEL_ACCOUNT_SID", user_id=current_user.id) or os.getenv("EXOTEL_ACCOUNT_SID")
            exotel_key = get_credential("EXOTEL_API_KEY", user_id=current_user.id) or os.getenv("EXOTEL_API_KEY")
            exotel_token = get_credential("EXOTEL_API_TOKEN", user_id=current_user.id) or os.getenv("EXOTEL_API_TOKEN")
            exophone = get_credential("EXOPHONE", user_id=current_user.id) or os.getenv("EXOPHONE")
            app_id = get_credential("EXOTEL_APP_ID", user_id=current_user.id) or os.getenv("EXOTEL_APP_ID")

            # ROBUST LEAD LOOKUP: If lead_id is missing, search by normalized phone number
            if not lead_id or lead_id == 0:
                normalized_to = normalize_phone(to)
                lead = session.exec(select(Lead).where(Lead.phone == normalized_to)).first()
                if lead:
                    lead_id = lead.id
                    logger.info(f"📋 [telephony] Found lead #{lead_id} ('{lead.name}') by phone lookup for call to {to}")
                    
                    # Log comprehensive context for debugging/robustness
                    ctx = get_comprehensive_lead_context(session, lead_id)
                    if ctx:
                        logger.info(f"📄 [telephony] Pre-call Lead Context ready for Lead #{lead_id}")
                else:
                    logger.info(f"❓ [telephony] No lead found for phone {to}. Proceeding with generic context.")
            elif lead_id and lead_id > 0:
                # If we have a lead_id, ensure we log its context
                ctx = get_comprehensive_lead_context(session, lead_id)
                if ctx:
                    logger.info(f"📄 [telephony] Proactive context loaded for Lead #{lead_id}")

            settings = session.exec(select(SystemSettings)).all()
            settings_dict = {s.key: s.value for s in settings}
            active_telephony = settings_dict.get("telephony_engine", "twilio")

        if active_telephony == "twilio":
            client = TwilioClient(sid, token)
            call = client.calls.create(
                url=f"https://{DOMAIN}/outgoing-call?lead_id={lead_id or 0}",
                to=to,
                from_=from_number
            )
            return {"message": "Twilio Call initiated", "call_sid": call.sid}
        
        elif active_telephony == "exotel":
            # Keys already fetched above using get_credential

            url = f"https://api.exotel.com/v1/Accounts/{exotel_sid}/Calls/connect.json"
            exoml_url = f"https://{DOMAIN}/exoml-start/{interaction_id or 'default'}?lead_id={lead_id or 0}&ngrok-skip-browser-warning=1"
            logger.info(f"🔗 Exotel ExoML URL: {exoml_url}")
            data = {
                "From": to,
                #"To": EXOPHONE,
                "CallerId": exophone,
                "Url": exoml_url,
                "CallType": "trans",
                "TimeLimit": "3600",
                "StatusCallback": f"https://{DOMAIN}/exotel-event"
            }
            auth = aiohttp.BasicAuth(exotel_key, exotel_token)
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(url, data=data, auth=auth) as resp:
                    result = await resp.json()
                    if resp.status not in [200, 201]:
                        raise Exception(f"Exotel Error: {result}")
                    return {"message": "Exotel Call initiated", "call_sid": result.get("Call", {}).get("Sid")}
        
        elif active_telephony == "enablex":
            # EnableX Outbound
            enablex_id = get_credential("ENABLEX_APP_ID", user_id=current_user.id) or os.getenv("ENABLEX_APP_ID")
            enablex_key = get_credential("ENABLEX_APP_KEY", user_id=current_user.id) or os.getenv("ENABLEX_APP_KEY")
            enablex_from = get_credential("ENABLEX_FROM_NUMBER", user_id=current_user.id) or os.getenv("ENABLEX_FROM_NUMBER")

            logger.info(f"Initiating EnableX Call to: {to}")
            enablex_auth = base64.b64encode(f"{enablex_id}:{enablex_key}".encode()).decode()
            headers = {
                "Authorization": f"Basic {enablex_auth}",
                "Content-Type": "application/json"
            }
            webhook_url = f"https://{DOMAIN}/enablex-event?ngrok-skip-browser-warning=1"
            if lead_id:
                 webhook_url += f"&lead_id={lead_id}"

            # EnableX expects numbers without + prefix (e.g., 911169040030)
            from_number = enablex_from.strip().replace("+", "") if enablex_from else "917550131495"
            # EnableX expects 'to' number without + prefix as well
            to_number = to.strip().replace("+", "")
            
            payload = {
                "name": "Rio-Assistant-Call",
                "from": from_number, 
                "to": to_number,
                "event_url": webhook_url
            }
            logger.info(f"📤 [EnableX Payload] {payload}")
            
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post("https://api.enablex.io/voice/v1/call", headers=headers, json=payload) as resp:
                    result = await resp.json()
                    logger.info(f"🔍 [EnableX Response] Status: {resp.status}, Body: {result}")
                    if resp.status not in [200, 201]:
                        raise Exception(f"EnableX API Error: {result}")
                    
                    # Create interaction record for Lead tracking
                    with Session(engine) as db_session:
                        interaction = Interaction(
                            lead_id=lead_id if lead_id else 0,
                            type="call",
                            content="Outbound Call (EnableX)",
                            timestamp=datetime.now(timezone.utc)
                        )
                        db_session.add(interaction)
                        db_session.commit()
                        db_session.refresh(interaction)
                        interaction_id = interaction.id

                    return {"message": "EnableX Call initiated", "voice_id": result.get("voice_id"), "interaction_id": interaction_id}
        
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported telephony: {active_telephony}")
            
    except Exception as e:
        logger.error(f"Error making call: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/exoml-start/{interaction_id}")
@router.post("/exoml-start/{interaction_id}")
async def exoml_start(request: Request, interaction_id: str = "default", lead_id: Optional[int] = None):
    logger.info(f"📥 ExoML request from {request.client.host} | params: {dict(request.query_params)}")
    # Strip any http/https prefix from DOMAIN — wss:// needs bare domain
    bare_domain = DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
    
    ws_url = f"wss://{bare_domain}/exotel-media-stream?interaction_id={interaction_id}&lead_id={lead_id or 0}&ngrok-skip-browser-warning=1"

    # Exotel ExoML — Stream is directly under Response, NOT inside <Connect>
    exoml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Please wait while I connect you.</Say>
    <Stream url="{ws_url}" />
</Response>"""

    logger.info(f"📋 ExoML served for interaction {interaction_id}: ws_url={ws_url}")
    return Response(content=exoml, media_type="text/xml", headers={"ngrok-skip-browser-warning": "true"})

@router.post("/enablex-event")
async def enablex_event(request: Request, lead_id: int = None):
    """Handles EnableX call lifecycle events."""
    data = await request.json()
    event_type = data.get("event") or data.get("state")
    voice_id = data.get("voice_id")

    if event_type == "connected":
        ws_domain = DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        ws_url = f"wss://{ws_domain}/enablex-media-stream?voice_id={voice_id}&lead_id={lead_id or 0}"
        
        enablex_id  = get_credential("ENABLEX_APP_ID")
        enablex_key = get_credential("ENABLEX_APP_KEY")
        enablex_auth = base64.b64encode(f"{enablex_id}:{enablex_key}".encode()).decode()
        headers = {"Authorization": f"Basic {enablex_auth}", "Content-Type": "application/json"}
        
        # payload = {"action": "streaming", "url": ws_url, "stream_type": "both", "play_on_connect": True}
        payload = {"url": ws_url}
        async with aiohttp.ClientSession() as session:
            url = f"https://api.enablex.io/voice/v1/call/{voice_id}/stream"
            # async with session.post(url, headers=headers, json=payload) as resp:
            async with session.put(url, headers=headers, json=payload) as resp:
                result = await resp.json()
                logger.info(f"EnableX Stream Initiation: {resp.status} | {result}")
                
    return {"status": "ok"}

@router.post("/exotel-event")
@router.get("/exotel-event")
async def exotel_event(request: Request):
    return "OK"

@router.post("/send-sms")
async def send_sms(to: str, message: str, current_user: User = Depends(RoleChecker(["admin", "user"]))):
    from utils.encryption import decrypt_value
    from twilio.rest import Client as TwilioClient
    try:
        with Session(engine) as session:
            sid = get_credential("TWILIO_ACCOUNT_SID", user_id=current_user.id) or os.getenv("TWILIO_ACCOUNT_SID")
            token = get_credential("TWILIO_AUTH_TOKEN", user_id=current_user.id) or os.getenv("TWILIO_AUTH_TOKEN")
            from_num = get_credential("PHONE_NUMBER_FROM", user_id=current_user.id) or os.getenv("PHONE_NUMBER_FROM")
            
            logger.info(f"📤 [telephony] Sending SMS via {sid[:6]}...")
            
            client = TwilioClient(sid, token)
            msg = client.messages.create(to=to, from_=from_num, body=message)
            return {"message": "SMS sent", "sid": msg.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
