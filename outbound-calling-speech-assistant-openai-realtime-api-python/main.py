import os
import json
import asyncio
import base64
import sys
import audioop

from fastapi import FastAPI, WebSocket, Request, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
from google import genai
from google.genai import types
from database import init_db, get_session, Lead, LeadCreate, engine
from sqlmodel import Session, select
from rag_service import search_knowledge_base

# Initialize DB on startup
init_db()

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3006"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ... (Previous code remains the same until Endpoints)

# CRM API Endpoints
@app.get("/leads", response_model=list[Lead])
async def get_leads(session: Session = Depends(get_session)):
    """Fetch all leads from the database."""
    leads = session.exec(select(Lead).order_by(Lead.created_at.desc())).all()
    return leads

@app.post("/leads", response_model=Lead)
async def create_lead(lead: LeadCreate, session: Session = Depends(get_session)):
    """Create a new lead."""
    db_lead = Lead.from_orm(lead)
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

@app.put("/leads/{lead_id}", response_model=Lead)
async def update_lead(lead_id: int, lead: LeadCreate, session: Session = Depends(get_session)):
    """Update a lead."""
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead_data = lead.dict(exclude_unset=True)
    for key, value in lead_data.items():
        setattr(db_lead, key, value)
        
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

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
- **Languages:** You are consistently multilingual.
    - **Detect the language** the user is speaking (English, Hindi, Tamil, Telugu, Malayalam, Urdu, or Sanskrit).
    - **Reply in the SAME language** the user spoke.
    - If the user switches language, you switch immediately.
    - Ensure technical terms (like "Samsung", "OLED", "VRF") are kept in English if appropriate for that language's colloquial usage.

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

# Mock Inventory Data
INVENTORY = {
    "samsung 55 tv": {"stock": 5, "price": "₹65,000"},
    "samsung s24": {"stock": 12, "price": "₹75,000"},
    "galaxy watch": {"stock": 0, "price": "₹25,000"},
    "vrf system": {"stock": 2, "price": "₹4,00,000", "note": "Requires installation team"},
}

def check_inventory(product_name: str):
    """
    Checks the stock status and price of a product in the warehouse.
    
    Args:
        product_name: The name of the product to check (e.g., 'Samsung 55 TV', 'S24').
    
    Returns:
        JSON string with stock details.
    """
    print(f"Tool Triggered: check_inventory({product_name})")
    product_key = product_name.lower()
    
    # Simple fuzzy match
    for key, data in INVENTORY.items():
        if key in product_key or product_key in key:
            return json.dumps({"product": key, "status": data})
    
    return json.dumps({"product": product_name, "status": "Not found in catalog", "available_items": list(INVENTORY.keys())})

def query_knowledge_base(query: str):
    """
    Searches the knowledge base for policies, warranty info, and general support questions.
    
    Args:
        query: The user's question or search term (e.g., 'What is the warranty on VRF?', 'Return policy').
    
    Returns:
        String containing relevant context/documents.
    """
    print(f"Tool Triggered: query_knowledge_base({query})")
    results = search_knowledge_base(query)
    if results:
        return f"Context found: {results}"
    if results:
        return f"Context found: {results}"
    return "No relevant info found in knowledge base."

def update_lead_tool(phone: str, notes: str, status: str = None):
    """
    Updates the CRM lead information for the given phone number.
    
    Args:
        phone: The customer's phone number.
        notes: New notes to append or save.
        status: (Optional) New status (e.g., 'Interested', 'Follow-up').
    """
    print(f"Tool Triggered: update_lead_tool({phone}, {status})")
    
    with Session(get_db_connection()) as session: # Re-using connection logic for tool, might need adjustment if using get_session generator
         # Actually database.py exposes 'engine'. Let's import engine or use a helper.
         # Reviewing database.py... it has 'engine'.
         pass
    
    # Let's fix the import first to get 'engine' or just use the existing get_db_connection logic if compatible, 
    # but database.py was refactored to SQLModel where get_session yields a session.
    # I will stick to a fresh session approach using the engine from database.
    return "Lead updated successfully."

# Refined implementation below
from database import engine 

def update_lead_tool(phone: str, notes: str, status: str = None):
    """
    Updates the CRM lead information for the given phone number.
    """
    print(f"Tool Triggered: update_lead_tool({phone})")
    with Session(engine) as session:
        statement = select(Lead).where(Lead.phone == phone)
        lead = session.exec(statement).first()
        
        if lead:
            if notes:
                lead.notes = (lead.notes or "") + f"\n[AI]: {notes}"
            if status:
                lead.status = status
            session.add(lead)
            session.commit()
            return f"Updated lead {lead.name}."
        else:
             # Create new lead if not exists? For now just report.
            return "Lead not found for this number."

tools = [check_inventory, query_knowledge_base, update_lead_tool]

# Emergency Safety
BLOCKED_NUMBERS = {"911", "112", "999"}



if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and PHONE_NUMBER_FROM and GEMINI_API_KEY):
    print("Error: Missing environment variables in .env")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})

@app.get("/", response_class=HTMLResponse)
async def index():
    return "<h1>Twilio + Gemini Voice Agent</h1><p>Server is running.</p>"

@app.post("/make-call")
async def make_call(to: str, lead_id: int = None):
    """Initiates an outbound call to the specified number."""
    if not DOMAIN:
        raise HTTPException(status_code=500, detail="DOMAIN environment variable not set")
    
    # Safety Check
    cleaned_number = to.replace("+", "").strip()
    if cleaned_number in BLOCKED_NUMBERS or to.strip() in BLOCKED_NUMBERS:
        raise HTTPException(status_code=400, detail="Emergency numbers are blocked for safety.")
    
    try:
        # Pass lead_id to the webhook
        webhook_url = f"https://{DOMAIN}/incoming-call"
        if lead_id:
            webhook_url += f"?lead_id={lead_id}"

        call = client.calls.create(
            to=to,
            from_=PHONE_NUMBER_FROM,
            url=webhook_url
        )
        return {"message": "Call initiated", "call_sid": call.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/incoming-call")
async def incoming_call(request: Request, lead_id: int = None):
    """Returns TwiML to connect the call to the WebSocket stream."""
    response = VoiceResponse()
    response.say("Connected to Gemini AI. Please start speaking.")
    connect = Connect()
    
    stream_url = f"wss://{DOMAIN}/media-stream"
    if lead_id:
        stream_url += f"?lead_id={lead_id}"
        
    connect.stream(url=stream_url)
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
async def handle_media_stream(websocket: WebSocket, lead_id: int = None):
    """Handles the WebSocket connection between Twilio and Gemini."""
    await websocket.accept()
    print(f"Twilio connected. Lead ID: {lead_id}")

    stream_sid = None
    
    # Dynamic Context Loading
    dynamic_instruction = SYSTEM_INSTRUCTION
    if lead_id:
        with Session(engine) as db_session:
            lead = db_session.get(Lead, lead_id)
            if lead:
                print(f"Loading context for: {lead.name}")
                context_note = f"\n\n**CURRENT CALL CONTEXT**\n" \
                               f"You are speaking with {lead.name}.\n" \
                               f"Phone: {lead.phone}\n" \
                               f"Status: {lead.status}\n" \
                               f"Previous Notes: {lead.notes or 'None'}\n" \
                               f"Goal: Update them on their inquiry and save any new notes using the 'update_lead_tool'."
                dynamic_instruction += context_note

    # Configuration for Gemini Session
    # Gemini usually expects PCM 16kHz or 24kHz. Twilio sends 8kHz mulaw.
    # We will need to resample/transcode.
    # For this implementation, we rely on Gemini's robust input handling if possible,
    # but strictly we should decode mulaw->pcm.
    
    model = "gemini-2.0-flash-exp"
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": types.Content(parts=[types.Part(text=dynamic_instruction)]),
        "speech_config": {
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}},
        },
        "tools": [types.Tool(function_declarations=[check_inventory, query_knowledge_base, update_lead_tool])]
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
                        
                        # Debug: Print audio energy (RMS) to see if we are receiving silence
                        rms = audioop.rms(pcm_8k, 2)
                        if rms > 100: # Only log if there's significant sound to avoid spam
                            print(f"Audio received (RMS: {rms})")
                        
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

                    # Handle Tool Call
                    tool_call = response.server_content.tool_call
                    if tool_call is not None:
                        print(f"Gemini requested tool: {tool_call.function_calls[0].name}")
                        for fc in tool_call.function_calls:
                            if fc.name == "check_inventory":
                                args = fc.args
                                result = check_inventory(args["product_name"])
                                
                                # Send result back to Gemini
                                tool_response = types.LiveClientToolResponse(
                                    function_responses=[types.FunctionResponse(
                                        name=fc.name,
                                        id=fc.id,
                                        response={"result": result}
                                    )]
                                )
                                print(f"Sending tool response: {result}")
                                await session.send(input=tool_response)
                            elif fc.name == "query_knowledge_base":
                                args = fc.args
                                result = query_knowledge_base(args["query"])
                                
                                tool_response = types.LiveClientToolResponse(
                                    function_responses=[types.FunctionResponse(
                                        name=fc.name, # Corrected: using fc.name dynamically is safer or string literal "query_knowledge_base"
                                        id=fc.id,
                                        response={"result": result}
                                    )]
                                )
                                print(f"Sending RAG response: {result[:50]}...")
                                await session.send(input=tool_response)

                            elif fc.name == "update_lead_tool":
                                args = fc.args
                                # Gemini might pass status as None/null, need to handle
                                result = update_lead_tool(
                                    phone=args.get("phone"), 
                                    notes=args.get("notes"),
                                    status=args.get("status")
                                )
                                
                                tool_response = types.LiveClientToolResponse(
                                    function_responses=[types.FunctionResponse(
                                        name=fc.name,
                                        id=fc.id,
                                        response={"result": result}
                                    )]
                                )
                                print(f"Sending CRM Update response: {result}")
                                await session.send(input=tool_response)

                    # Handle Audio
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
                import traceback
                traceback.print_exc()

        await asyncio.gather(receive_from_twilio(), send_to_twilio())

if __name__ == "__main__":
    import uvicorn
    # Twilio does not support WebSocket Ping/Pong, so we must disable it in Uvicorn
    # to prevent "keepalive ping timeout" errors.
    uvicorn.run(app, host="0.0.0.0", port=PORT, ws_ping_interval=None, ws_ping_timeout=None, timeout_keep_alive=60)
