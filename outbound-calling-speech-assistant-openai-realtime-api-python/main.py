import os
import json
import asyncio
import base64
import sys
import audioop

from fastapi import FastAPI, WebSocket, Request, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

# Gemini System Instruction
# Gemini System Instruction
SYSTEM_INSTRUCTION = """
You are Rio, a friendly and knowledgeable AI sales assistant for Yexis Electronics.
Your goal is to assist customers with Sales & Distribution inquiries.

**About Yexis Electronics:**
- We are an authorized B2B Distributor and Samsung wholesale distributor/dealer for Southern India.
- **Key Products:**
    - **Mobility:** Samsung Smartphones, Tablets, and Accessories.
    - **Displays:** LED/OLED/QLED TVs, High-res Monitors, Smart Monitors, Interactive Displays, Video Walls.
    - **HVAC:** Commercial Split ACs, VRF DVM, Chillers, Ventilation.
    - **Computing:** Samsung Laptops, Memory, Storage.
    - **AV Solutions:** Video Conferencing, Meeting Room Audio, Specialized AV gear.
- **Services:** Consultative Design, Implementation, AMC (Annual Maintenance), Onsite Support.
- **Industries Served:** IT/ITES, Healthcare, Education, Manufacturing, Hospitality, Government, Retail.
- **Location:** Chennai, India (Redhills).

**Your Personality:**
- Name: Rio.
- Tone: Professional, enthusiastic, warm, and helpful.
- Behavior: detailed and conversational.
- Objective: Explain our products/services and ask if they would like to request a quote or schedule a consultation.

**Conversation Style:**
- Keep responses concise (1-3 sentences) suitable for voice.
- Don't list everything at once; ask follow-up questions to understand their needs.
"""

# Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
PHONE_NUMBER_FROM = os.getenv("PHONE_NUMBER_FROM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
DOMAIN = os.getenv("DOMAIN") # e.g. "your-id.ngrok-free.app"
if DOMAIN:
    DOMAIN = DOMAIN.replace("http://", "").replace("https://", "").replace("/", "")
PORT = int(os.getenv("PORT", 6060))

# Emergency Safety
BLOCKED_NUMBERS = {"911", "112", "999"}

app = FastAPI()

if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and PHONE_NUMBER_FROM and GEMINI_API_KEY):
    print("Error: Missing environment variables in .env")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})

@app.get("/", response_class=HTMLResponse)
async def index():
    return "<h1>Twilio + Gemini Voice Agent</h1><p>Server is running.</p>"

@app.post("/make-call")
async def make_call(to: str):
    """Initiates an outbound call to the specified number."""
    if not DOMAIN:
        raise HTTPException(status_code=500, detail="DOMAIN environment variable not set")
    
    # Safety Check
    cleaned_number = to.replace("+", "").strip()
    if cleaned_number in BLOCKED_NUMBERS or to.strip() in BLOCKED_NUMBERS:
        raise HTTPException(status_code=400, detail="Emergency numbers are blocked for safety.")
    
    try:
        call = client.calls.create(
            to=to,
            from_=PHONE_NUMBER_FROM,
            url=f"https://{DOMAIN}/incoming-call"
        )
        return {"message": "Call initiated", "call_sid": call.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/incoming-call")
async def incoming_call(request: Request):
    """Returns TwiML to connect the call to the WebSocket stream."""
    response = VoiceResponse()
    response.say("Connected to Gemini AI. Please start speaking.")
    connect = Connect()
    connect.stream(url=f"wss://{DOMAIN}/media-stream")
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.post("/send-sms")
async def send_sms(to: str, message: str):
    """Sends an outbound SMS."""
    # Safety Check
    cleaned_number = to.replace("+", "").strip()
    if cleaned_number in BLOCKED_NUMBERS or to.strip() in BLOCKED_NUMBERS:
        raise HTTPException(status_code=400, detail="Emergency numbers are blocked.")

    try:
        msg = client.messages.create(
            to=to,
            from_=PHONE_NUMBER_FROM,
            body=message
        )
        return {"message": "SMS sent", "sid": msg.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/incoming-sms")
async def incoming_sms(request: Request):
    """Handles incoming SMS webhooks from Twilio."""
    form_data = await request.form()
    sender = form_data.get("From")
    body = form_data.get("Body")
    
    print(f"Received SMS from {sender}: {body}")
    
    # Simple Auto-Reply
    response = MessagingResponse()
    response.message(f"Thanks for your message: '{body}'. Gemini Voice Agent received it.")
    
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Handles the WebSocket connection between Twilio and Gemini."""
    await websocket.accept()
    print("Twilio connected")

    stream_sid = None
    
    # Configuration for Gemini Session
    # Gemini usually expects PCM 16kHz or 24kHz. Twilio sends 8kHz mulaw.
    # We will need to resample/transcode.
    # For this implementation, we rely on Gemini's robust input handling if possible,
    # but strictly we should decode mulaw->pcm.
    
    model = "gemini-2.0-flash-exp"
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": types.Content(parts=[types.Part(text=SYSTEM_INSTRUCTION)])
    }

    async with gemini_client.aio.live.connect(model=model, config=config) as session:
        print("Connected to Gemini Live API")
        
        async def receive_from_twilio():
            nonlocal stream_sid
            # Maintain state for consistent audio processing
            # state is used by ratecv to handle fractional samples between chunks
            downstream_state = None 

            try:
                async for message in websocket.iter_text():
                    data = json.loads(message)
                    if data["event"] == "start":
                        stream_sid = data["start"]["streamSid"]
                        print(f"Stream started: {stream_sid}")
                    elif data["event"] == "media":
                        media_payload = data["media"]["payload"]
                        chunk = base64.b64decode(media_payload)
                        
                        # Transcoding: Twilio (8kHz mulaw) -> Gemini (16kHz PCM)
                        # 1. Decode mulaw to 16-bit PCM (8kHz)
                        pcm_8k = audioop.ulaw2lin(chunk, 2)
                        
                        # 2. Upsample 8kHz -> 16kHz
                        # simple way: ratecv(fragment, width, nchannels, inrate, outrate, state)
                        pcm_16k, downstream_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, downstream_state)
                        
                        await session.send(input={"data": pcm_16k, "mime_type": "audio/pcm"}, end_of_turn=False)
                        
                    elif data["event"] == "stop":
                        print("Stream stopped")
            except WebSocketDisconnect:
                print("Twilio disconnected")
            except Exception as e:
                print(f"Error receiving from Twilio: {e}")

        async def send_to_twilio():
            # Maintain state for consistent audio processing
            upstream_state = None

            try:
                async for response in session.receive():
                    if response.server_content is None:
                        continue

                    model_turn = response.server_content.model_turn
                    if model_turn is not None:
                        for part in model_turn.parts:
                            if part.inline_data is not None:
                                # Audio back from Gemini
                                audio_data = part.inline_data.data 
                                
                                # Transcoding: Gemini (24kHz PCM) -> Twilio (8kHz mulaw)
                                # 1. Downsample 24kHz -> 8kHz
                                # Gemini Live usually returns 24kHz. If voice sounds weird, check this rate.
                                pcm_8k, upstream_state = audioop.ratecv(audio_data, 2, 1, 24000, 8000, upstream_state)
                                
                                # 2. Encode 16-bit PCM -> 8-bit mulaw
                                mulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                
                                b64_audio = base64.b64encode(mulaw_8k).decode("utf-8")
                                
                                await websocket.send_json({
                                    "event": "media",
                                    "streamSid": stream_sid,
                                    "media": {
                                        "payload": b64_audio
                                    }
                                })
            except Exception as e:
                print(f"Error sending to Twilio: {e}")

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

if __name__ == "__main__":
    import uvicorn
    # Twilio does not support WebSocket Ping/Pong, so we must disable it in Uvicorn
    # to prevent "keepalive ping timeout" errors.
    uvicorn.run(app, host="0.0.0.0", port=PORT, ws_ping_interval=None, ws_ping_timeout=None)
