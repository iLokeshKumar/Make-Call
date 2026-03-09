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
from utils.config import (
    DOMAIN, twilio_client, PHONE_NUMBER_FROM, 
    EXOTEL_ACCOUNT_SID, EXOTEL_API_KEY, EXOTEL_API_TOKEN,
    ENABLEX_APP_ID, ENABLEX_APP_KEY, EXOPHONE, EXOTEL_APP_ID
)
from auth import RoleChecker

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Telephony"])

@router.post("/incoming-call")
async def incoming_call(request: Request, lead_id: int = None):
    """Returns TwiML to connect the call to the WebSocket stream."""
    response = VoiceResponse()

    # Create an interaction record
    with Session(engine) as session:
        interaction = Interaction(
            lead_id=lead_id if lead_id else 0,
            type="call",
            content="Incoming call",
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
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@router.post("/make-call")
async def make_call(to: str, lead_id: Optional[int] = None, engine_type: str = "mistral-cartesia", interaction_id: Optional[str] = None):
    """Initiates an outbound call via selected telephony engine."""
    try:
        # Standardize number (Handle Indian numbers specifically)
        clean_number = "".join(filter(str.isdigit, to))
        
        if to.startswith("+"):
            # Already E.164, leave as is
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
            settings = session.exec(select(SystemSettings)).all()
            settings_dict = {s.key: s.value for s in settings}
            active_telephony = settings_dict.get("telephony_engine", "twilio")

        if active_telephony == "twilio":
            call = twilio_client.calls.create(
                url=f"https://{DOMAIN}/incoming-call?lead_id={lead_id or 0}",
                to=to,
                from_=PHONE_NUMBER_FROM
            )
            return {"message": "Twilio Call initiated", "call_sid": call.sid}
        
        elif active_telephony == "exotel":
            url = f"https://api.exotel.com/v1/Accounts/{EXOTEL_ACCOUNT_SID}/Calls/connect.json"
            exoml_url = f"https://{DOMAIN}/exoml-start/{interaction_id or 'default'}?lead_id={lead_id or 0}"
            exotel_app_url = f"http://my.exotel.com/{EXOTEL_ACCOUNT_SID}/exoml/start/{EXOTEL_APP_ID}"
            logger.info(f"🔗 Exotel ExoML URL: {exoml_url}")
            logger.info(f"🔗 Exotel App URL: {exotel_app_url}")
            data = {
                "From": to,
                #"To": EXOPHONE,
                "CallerId": EXOPHONE,
                "Url": exotel_app_url,
                "CallType": "trans",
                "TimeLimit": "3600",
                "StatusCallback": f"https://{DOMAIN}/exotel-event"
            }
            auth = aiohttp.BasicAuth(EXOTEL_API_KEY, EXOTEL_API_TOKEN)
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post(url, data=data, auth=auth) as resp:
                    result = await resp.json()
                    if resp.status not in [200, 201]:
                        raise Exception(f"Exotel Error: {result}")
                    return {"message": "Exotel Call initiated", "call_sid": result.get("Call", {}).get("Sid")}
        
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
    
    ws_url = f"wss://{bare_domain}/exotel-media-stream?interaction_id={interaction_id}&lead_id={lead_id or 0}"

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
        
        enablex_auth = base64.b64encode(f"{ENABLEX_APP_ID}:{ENABLEX_APP_KEY}".encode()).decode()
        headers = {"Authorization": f"Basic {enablex_auth}", "Content-Type": "application/json"}
        
        payload = {"action": "streaming", "url": ws_url, "stream_type": "both", "play_on_connect": True}
        async with aiohttp.ClientSession() as session:
            url = f"https://api.enablex.io/voice/v1/call/{voice_id}/action"
            async with session.post(url, headers=headers, json=payload) as resp:
                logger.info(f"EnableX Stream Initiation: {resp.status}")
                
    return {"status": "ok"}

@router.post("/exotel-event")
@router.get("/exotel-event")
async def exotel_event(request: Request):
    return "OK"

@router.post("/send-sms")
async def send_sms(to: str, message: str):
    try:
        msg = twilio_client.messages.create(to=to, from_=PHONE_NUMBER_FROM, body=message)
        return {"message": "SMS sent", "sid": msg.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
