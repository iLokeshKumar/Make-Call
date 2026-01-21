import os
import json
import asyncio
import base64
import sys
import audioop
import pandas as pd
import io
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, Request, HTTPException, Depends, WebSocketDisconnect, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import requests
from google import genai
from google.genai import types
from mistralai import Mistral as MistralClient
try:
    from deepgram import DeepgramClient
    # v5 SDK locations
    from deepgram.listen.live.v1 import LiveOptions
    try:
        from deepgram import LiveTranscriptionEvents
    except Exception:
        LiveTranscriptionEvents = None
except ImportError:
    try:
        from deepgram import DeepgramClient
        # Older SDKs
        from deepgram.options import LiveOptions
        try:
            from deepgram import LiveTranscriptionEvents
        except Exception:
            LiveTranscriptionEvents = None
    except ImportError:
        DeepgramClient = globals().get('DeepgramClient')
        LiveOptions = None
        LiveTranscriptionEvents = None
import aiohttp
from database import init_db, get_session, Lead, LeadCreate, engine, Interaction, Product, SystemSettings
from sqlmodel import Session, select, func, text, col, SQLModel
from rag_service import search_knowledge_base

# Initialize DB on startup
init_db()

from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000", 
        "http://localhost:3006",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3006"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CRM API Endpoints
@app.get("/leads", response_model=list[Lead])
async def get_leads(session: Session = Depends(get_session)):
    """Fetch all leads from the database."""
    leads = session.exec(select(Lead).order_by(Lead.created_at.desc())).all()
    return leads

@app.post("/leads", response_model=Lead)
async def create_lead(lead: LeadCreate, session: Session = Depends(get_session)):
    """Create a new lead."""
    db_lead = Lead.model_validate(lead)
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

@app.delete("/leads/{lead_id}")
async def delete_lead(lead_id: int, session: Session = Depends(get_session)):
    """Delete a lead."""
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    session.delete(db_lead)
    session.commit()
    return {"message": "Lead deleted"}

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

class ApolloSearch(SQLModel):
    keywords: str

@app.post("/leads/fetch-apollo")
async def fetch_apollo(search: ApolloSearch, session: Session = Depends(get_session)):
    """Fetches leads from Apollo.io (Organizations) and adds them to DB."""
    if not APOLLO_API_KEY:
        raise HTTPException(status_code=500, detail="APOLLO_API_KEY not configured.")

    url = "https://api.apollo.io/v1/organizations/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY
    }
    payload = {
        "q_organization_name": search.keywords,
        "page": 1,
        "per_page": 10 
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        
        if response.status_code != 200:
             raise HTTPException(status_code=response.status_code, detail=data.get("error", "Apollo API Error"))

        organizations = data.get("organizations", [])
        leads_added = 0
        
        for org in organizations:
            # Map Organization to Lead
            # Name -> Name, Phone -> Phone
            name = org.get("name")
            phone = org.get("phone_number") or "N/A" # Many orgs might miss phone
            
            if not name or phone == "N/A":
                continue

            # Basic Duplicate Check
            existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
            if not existing:
                new_lead = Lead(
                    name=name,
                    phone=phone,
                    email=None, 
                    # Store domain in notes for now
                    notes=f"Apollo Import: {org.get('primary_domain', '')}",
                    source="Apollo API",
                    status="New"
                )
                session.add(new_lead)
                leads_added += 1
        
        session.commit()
        return {"message": f"Successfully imported {leads_added} leads from Apollo.", "total_found": len(organizations)}

    except Exception as e:
        print(f"Apollo Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Dashboard Stats Endpoint
@app.get("/dashboard/stats")
async def get_dashboard_stats(session: Session = Depends(get_session)):
    """Fetch aggregated stats for the dashboard."""
    total_leads = session.exec(select(func.count(Lead.id))).one()
    
    # Calls today (created_at >= start of today). 
    # SQLite doesn't have easy date functions like PG, so we might check python side or basic sql.
    # PROPER WAY: use date(now).
    # For compatibility/simplicity, we'll try a basic filter or fetch all and filter (for small scale).
    # Better: SQLModel standard way.
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    calls_today = session.exec(select(func.count(Interaction.id)).where(Interaction.type == "call").where(Interaction.timestamp >= today_start)).one()
    
    converted = session.exec(select(func.count(Lead.id)).where(Lead.status == "Converted")).one()
    follow_up = session.exec(select(func.count(Lead.id)).where(Lead.status == "Follow-up")).one()
    
    return {
        "total_leads": total_leads,
        "calls_today": calls_today,
        "converted": converted,
        "follow_up": follow_up
    }

@app.get("/interactions")
async def get_interactions(session: Session = Depends(get_session)):
    """Fetch call history."""
    interactions = session.exec(select(Interaction).order_by(Interaction.timestamp.desc())).all()
    return interactions

# AI Instructions and Configuration are now loaded dynamically from the database.
# See SystemSettings model in database.py.

# Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
PHONE_NUMBER_FROM = os.getenv("PHONE_NUMBER_FROM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "CwhOLp6mAE7h9asvUURR")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")

# EnableX Configuration
ENABLEX_APP_ID = os.getenv("EnableX_App_ID")
ENABLEX_APP_KEY = os.getenv("EnableX_App_Key")
ENABLEX_FROM_NUMBER = os.getenv("ENABLEX_FROM_NUMBER")

DOMAIN = os.getenv("DOMAIN") # e.g. "your-id.ngrok-free.app"
if DOMAIN:
    DOMAIN = DOMAIN.replace("http://", "").replace("https://", "").replace("/", "")
PORT = int(os.getenv("PORT", 6060))

def check_inventory(product_name: str):
    """
    Checks the stock status and price of a product in the warehouse from the database.
    """
    print(f"Tool Triggered: check_inventory({product_name})")
    
    with Session(engine) as session:
        # Simple ilike or substring search
        search_term = f"%{product_name.lower()}%"
        statement = select(Product).where(col(Product.name).ilike(search_term))
        product = session.exec(statement).first()
        
        if product:
            return json.dumps({
                "product": product.name,
                "stock": product.stock,
                "price": product.price,
                "note": product.note or ""
            })
            
        # If not found, suggest available categories or items
        all_products = session.exec(select(Product.name)).all()
        return json.dumps({
            "product": product_name, 
            "status": "Not found in catalog", 
            "available_items": all_products[:10] # limit to 10 for voice brevity
        })

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

# Lead tool implementation
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
# AI Clients
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})
mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
deepgram_client = DeepgramClient(api_key=DEEPGRAM_API_KEY) if DeepgramClient else None

from fastapi.middleware.cors import CORSMiddleware

# Enable CORS for Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all for demo purposes (or specific localhost ports)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    
    
    # Get active telephony engine
    with Session(engine) as db_session:
        telephony_setting = db_session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first()
        active_telephony = telephony_setting.value if telephony_setting else "twilio"

    try:
        if active_telephony == "enablex":
            # EnableX Outbound
            print(f"Initiating EnableX Call to: {to}")
            enablex_auth = base64.b64encode(f"{ENABLEX_APP_ID}:{ENABLEX_APP_KEY}".encode()).decode()
            headers = {
                "Authorization": f"Basic {enablex_auth}",
                "Content-Type": "application/json"
            }
            webhook_url = f"https://{DOMAIN}/enablex-event"
            if lead_id:
                 webhook_url += f"?lead_id={lead_id}"

            payload = {
                "name": "Rio-Assistant-Call",
                "from": ENABLEX_FROM_NUMBER if ENABLEX_FROM_NUMBER else "917550131495", 
                "to": to,
                "event_url": webhook_url
            }
            
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post("https://api.enablex.io/voice/v1/call", headers=headers, json=payload) as resp:
                    result = await resp.json()
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
            # Twilio Outbound
            webhook_url = f"https://{DOMAIN}/incoming-call"
            if lead_id:
                webhook_url += f"?lead_id={lead_id}"

            call = client.calls.create(
                to=to,
                from_=PHONE_NUMBER_FROM,
                url=webhook_url
            )
            return {"message": "Twilio Call initiated", "call_sid": call.sid}
    except Exception as e:
        print(f"Error making call: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/enablex-event")
async def enablex_event(request: Request, lead_id: int = None):
    """Handles EnableX call lifecycle events."""
    data = await request.json()
    # Log full payload for debugging
    print(f"📞 EnableX Webhook Data: {json.dumps(data)}")
    
    # EnableX uses "state" for call lifecycle events
    event_type = data.get("event") or data.get("state")
    voice_id = data.get("voice_id")
    print(f"📞 EnableX Event Key: {event_type} | Voice ID: {voice_id}")

    if event_type == "connected":
        # Initiation of media stream
        enablex_auth = base64.b64encode(f"{ENABLEX_APP_ID}:{ENABLEX_APP_KEY}".encode()).decode()
        headers = {
            "Authorization": f"Basic {enablex_auth}",
            "Content-Type": "application/json"
        }
        
        # Clean domain for WebSocket (remove https://)
        ws_domain = DOMAIN.replace("https://", "").replace("http://", "")
        stream_payload = {
            "wss_host": f"wss://{ws_domain}/enablex-media-stream?voice_id={voice_id}&lead_id={lead_id}",
            "play_on_connect": True
        }
        async with aiohttp.ClientSession() as session:
            # EnableX uses PUT for starting a stream
            async with session.put(f"https://api.enablex.io/voice/v1/call/{voice_id}/stream", headers=headers, json=stream_payload) as resp:
                print(f"🚀 EnableX Stream Request sent (PUT). Status: {resp.status}")
                
    return {"status": "ok"}

@app.post("/incoming-call")
async def incoming_call(request: Request, lead_id: int = None):
    """Returns TwiML to connect the call to the WebSocket stream."""
    response = VoiceResponse()

    # Create an interaction record
    with Session(engine) as session:
        interaction = Interaction(
            lead_id=lead_id if lead_id else 0, # 0 for unknown
            type="call",
            content="Incoming call",
            timestamp=datetime.now(timezone.utc)
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction) # Get the ID
        # Read active engine from settings to tailor the prompt
        engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
        active_engine = (engine_setting.value if engine_setting else "gemini").strip().lower()

    # Announce based on engine
    if active_engine == "mistral":
        response.say("Connected to AI assistant from Yexis Electronics by Mistral. Please start speaking.")
    elif active_engine == "gemini":
        response.say("Connected to AI assistant from Yexis Electronics by Google. Please start speaking.")
    else:
        response.say("Connected to Yexis Electronics AI assistant. Please start speaking.")
    connect = Connect()
    stream = connect.stream(url=f'wss://{request.url.netloc}/media-stream')
    stream.parameter(name="interaction_id", value=str(interaction.id))
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

@app.post("/leads/upload")
async def upload_leads(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """Uploads an Excel or CSV file of leads."""
    contents = await file.read()
    
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Invalid file format. Please upload .csv or .xlsx")
        
        # Standardize columns (basic mapping)
        # Expected: Name, Phone, Email (optional), Notes (optional)
        df.columns = [c.lower().strip() for c in df.columns]
        
        leads_added = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                # Basic validation
                name = row.get("name")
                phone = str(row.get("phone", "")).replace(".0", "").strip() 
                email = row.get("email") if "email" in row else None
                notes = row.get("notes") if "notes" in row else None
                
                if not name or not phone:
                    continue
                    
                # Duplicate check
                existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
                if not existing:
                    new_lead = Lead(
                        name=name,
                        phone=phone,
                        email=email,
                        notes=notes,
                        source="Excel Upload",
                        status="New"
                    )
                    session.add(new_lead)
                    leads_added += 1
            except Exception as e:
                errors.append(f"Row {index}: {e}")
                
        session.commit()
        return {"message": f"Successfully added {leads_added} leads.", "errors": errors}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

class ApolloSearch(SQLModel):
    keywords: str

@app.post("/leads/fetch-apollo")
async def fetch_apollo(search: ApolloSearch, session: Session = Depends(get_session)):
    """Fetches leads from Apollo.io (Organizations) and adds them to DB."""
    if not APOLLO_API_KEY:
        raise HTTPException(status_code=500, detail="APOLLO_API_KEY not configured.")

    url = "https://api.apollo.io/v1/organizations/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY
    }
    payload = {
        "q_organization_name": search.keywords,
        "page": 1,
        "per_page": 10 
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        
        if response.status_code != 200:
             raise HTTPException(status_code=response.status_code, detail=data.get("error", "Apollo API Error"))

        organizations = data.get("organizations", [])
        leads_added = 0
        
        for org in organizations:
            # Map Organization to Lead
            # Name -> Name, Phone -> Phone
            name = org.get("name")
            phone = org.get("phone_number") or "N/A" # Many orgs might miss phone
            
            if not name or phone == "N/A":
                continue

            # Basic Duplicate Check
            existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
            if not existing:
                new_lead = Lead(
                    name=name,
                    phone=phone,
                    email=None, # Or org.get("primary_domain")
                    notes=f"Apollo Import: {org.get('primary_domain')}",
                    source="Apollo API",
                    status="New"
                )
                session.add(new_lead)
                leads_added += 1
        
        session.commit()
        return {"message": f"Successfully imported {leads_added} leads from Apollo.", "total_found": len(organizations)}

    except Exception as e:
        print(f"Apollo Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/leads", response_model=list[Lead])
async def get_leads(session: Session = Depends(get_session)):
    """Fetch all leads."""
    return session.exec(select(Lead)).all()

# Management Endpoints (Phase 3)
@app.get("/inventory", response_model=list[Product])
async def get_inventory(session: Session = Depends(get_session)):
    """Fetch all products."""
    return session.exec(select(Product)).all()

@app.post("/inventory", response_model=Product)
async def upsert_product(product: Product, session: Session = Depends(get_session)):
    """Add or update a product."""
    if product.id:
        db_p = session.get(Product, product.id)
        if db_p:
            for k, v in product.dict(exclude_unset=True).items():
                setattr(db_p, k, v)
        else:
            db_p = Product.model_validate(product)
    else:
        db_p = Product.model_validate(product)
        
    session.add(db_p)
    session.commit()
    session.refresh(db_p)
    return db_p

@app.delete("/inventory/{product_id}")
async def delete_product(product_id: int, session: Session = Depends(get_session)):
    """Delete a product."""
    db_p = session.get(Product, product_id)
    if not db_p:
        raise HTTPException(status_code=404, detail="Product not found")
    session.delete(db_p)
    session.commit()
    return {"message": "Product deleted"}

@app.get("/settings")
async def get_settings(session: Session = Depends(get_session)):
    """Fetch system settings."""
    instruction = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    engine = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    telephony = session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first()
    return {
        "system_instruction": instruction.value if instruction else "",
        "voice_engine": engine.value if engine else "gemini",
        "telephony_engine": telephony.value if telephony else "twilio"
    }

@app.patch("/settings")
async def update_settings(data: dict, session: Session = Depends(get_session)):
    """Update system settings."""
    for key, value in data.items():
        db_s = session.exec(select(SystemSettings).where(SystemSettings.key == key)).first()
        if not db_s:
            db_s = SystemSettings(key=key, value=str(value))
        else:
            db_s.value = str(value)
        session.add(db_s)
    
    session.commit()
    return {"message": "Settings updated"}


class TelephonyCommunicator:
    async def receive(self): pass
    async def send_media(self, b64_audio): pass

class TwilioCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = None
    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                yield data
        except Exception:
            yield {"event": "stop"}
    async def send_media(self, b64_audio):
        if self.stream_sid:
            await self.websocket.send_json({"event": "media", "streamSid": self.stream_sid, "media": {"payload": b64_audio}})

class EnableXCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                # EnableX often sends JSON with "data" key as base64
                # We need to verify if it's text or binary. iter_text() works for text.
                print(f"⏬ EnableX WS Received: {message[:100]}...")
                try:
                    data = json.loads(message)
                    # Map to Twilio-like events for minimal pipeline change
                    if "data" in data:
                        yield {"event": "media", "media": {"payload": data["data"]}}
                    elif data.get("event") == "stop" or data.get("state") == "disconnected":
                        yield {"event": "stop"}
                except json.JSONDecodeError:
                    # If it's not JSON, maybe it's raw binary? But iter_text was used.
                    print("⚠️ EnableX WS: Message is not valid JSON")
                    yield {"event": "media", "media": {"payload": base64.b64encode(message.encode()).decode() if isinstance(message, str) else base64.b64encode(message).decode()}}
        except Exception as e:
            print(f"❌ EnableX WS Receive Error: {e}")
            yield {"event": "stop"}
    async def send_media(self, b64_audio):
        # EnableX expects raw binary or JSON with data
        # Verification: EnableX Voice Server Media Stream API docs
        payload = {"event": "media", "data": b64_audio}
        print(f"⏫ EnableX WS Sending Media: {len(b64_audio)} chars")
        await self.websocket.send_json(payload)

async def gemini_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator):
    """Handles the Native Multimodal Live API logic for Gemini."""
    model = "models/gemini-2.0-flash-exp"
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": types.Content(parts=[types.Part(text=dynamic_instruction)]),
        "speech_config": {
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}},
        },
        "tools": [check_inventory, query_knowledge_base, update_lead_tool]
    }

    try:
        async with gemini_client.aio.live.connect(model=model, config=config) as gemini_session:
            async def receive_from_telephony():
                nonlocal interaction_id
                downstream_state = None 
                async for data in communicator.receive():
                    if data["event"] == "start":
                        if isinstance(communicator, TwilioCommunicator):
                            communicator.stream_sid = data["start"]["streamSid"]
                            custom_params = data["start"].get("customParameters", {})
                            if not interaction_id: interaction_id = custom_params.get("interaction_id")
                    elif data["event"] == "media":
                        media_payload = data["media"]["payload"]
                        chunk = base64.b64decode(media_payload)
                        pcm_8k = audioop.ulaw2lin(chunk, 2)
                        pcm_16k, downstream_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, downstream_state)
                        await gemini_session.send(input={"data": pcm_16k, "mime_type": "audio/pcm"}, end_of_turn=False)
                    elif data["event"] == "stop":
                        break

            async def send_to_telephony():
                upstream_state = None
                try:
                    async for response in gemini_session.receive():
                        if response.server_content and response.server_content.model_turn:
                            for part in response.server_content.model_turn.parts:
                                if getattr(part, 'function_call', None):
                                    fc = part.function_call
                                    result = await run_tool(fc.name, fc.args, transcript_accumulator, interaction_id)
                                    await gemini_session.send(input=types.LiveClientToolResponse(
                                        function_responses=[types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result})]
                                    ))
                                
                                if getattr(part, 'inline_data', None):
                                    audio_data = part.inline_data.data 
                                    pcm_8k, upstream_state = audioop.ratecv(audio_data, 2, 1, 24000, 8000, upstream_state)
                                    mulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                    b64_audio = base64.b64encode(mulaw_8k).decode("utf-8")
                                    await communicator.send_media(b64_audio)
                                
                                if getattr(part, 'text', None):
                                    transcript_accumulator.append(f"Rio: {part.text}")
                                    save_transcript(interaction_id, transcript_accumulator)
                except Exception as e:
                    print(f"Telephony Send Error: {e}")

            await asyncio.gather(receive_from_telephony(), send_to_telephony())
    except Exception as e:
        print(f"Gemini Pipeline Error: {e}")

@app.websocket("/enablex-media-stream")
async def handle_enablex_media_stream(websocket: WebSocket, session: Session = Depends(get_session)):
    """Handles EnableX WebSocket media stream."""
    await websocket.accept()
    voice_id = websocket.query_params.get("voice_id")
    lead_id = websocket.query_params.get("lead_id")
    
    # Find interaction_id for this voice_id/lead_id
    interaction_id = None
    if lead_id:
        with Session(engine) as db_session:
            # Get latest interaction for this lead
            db_i = db_session.exec(select(Interaction).where(Interaction.lead_id == int(lead_id)).order_by(Interaction.timestamp.desc())).first()
            if db_i: interaction_id = db_i.id

    transcript_accumulator = []
    
    settings = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    dynamic_instruction = settings.value if settings else "You are a helpful assistant."
    engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    active_engine = engine_setting.value if engine_setting else "gemini"
    
    print(f"EnableX connected to media-stream WS | Voice ID: {voice_id} | Interaction: {interaction_id}")
    
    communicator = EnableXCommunicator(websocket)
    if active_engine == "mistral":
        await mistral_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator)
    else:
        await gemini_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator)

async def run_tool(name, args, transcript_accumulator, interaction_id):
    """Shared tool runner for all pipelines."""
    result = "Unknown tool"
    if name == "check_inventory":
        result = check_inventory(args["product_name"])
        transcript_accumulator.append(f"[System]: Checked inventory for '{args['product_name']}' -> {result}")
    elif name == "query_knowledge_base":
        result = query_knowledge_base(args["query"])
        transcript_accumulator.append(f"[System]: Queried knowledge base for '{args['query']}'")
    elif name == "update_lead_tool":
        result = update_lead_tool(phone=args.get("phone"), notes=args.get("notes"), status=args.get("status"))
        transcript_accumulator.append(f"[System]: Updated lead info (Status: {args.get('status')})")
    
    save_transcript(interaction_id, transcript_accumulator)
    return result

def save_transcript(interaction_id, transcript_accumulator):
    """Saves transcript to DB."""
    if interaction_id:
        try:
            with Session(engine) as db_session:
                db_i = db_session.get(Interaction, int(interaction_id))
                if db_i:
                    transcript_text = "\n".join(transcript_accumulator)
                    db_i.transcript = transcript_text
                    db_session.add(db_i)
                    db_session.commit()
                    print(f"✅ Transcript saved for Interaction {interaction_id} ({len(transcript_accumulator)} lines, {len(transcript_text)} chars)")
                else:
                    print(f"⚠️ Interaction {interaction_id} not found in DB for transcript saving.")
        except Exception as e:
            print(f"❌ DB Error saving transcript: {e}")
    else:
        print("⚠️ No interaction_id provided to save_transcript")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket, session: Session = Depends(get_session)):
    """Handles the WebSocket connection and dispatches to the correct voice engine."""
    await websocket.accept()
    

    interaction_id = websocket.query_params.get("interaction_id")
    transcript_accumulator = []
    
    # Load dynamic instruction and engine selection
    settings = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    dynamic_instruction = settings.value if settings else "You are a helpful assistant."
    
    engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    active_engine = engine_setting.value if engine_setting else "gemini"
    
    print(f"Twilio connected to media-stream WS (Engine: {active_engine.upper()}) | Interaction ID: {interaction_id}")

    if interaction_id:
        try:
            db_interaction = session.get(Interaction, int(interaction_id))
            if db_interaction and db_interaction.lead_id:
                lead = session.get(Lead, db_interaction.lead_id)
                if lead:
                    context_note = f"\n\n**CURRENT CALL CONTEXT**\nSpeak with {lead.name}. Status: {lead.status}. Goal: Update them."
                    dynamic_instruction += context_note
        except Exception as e:
            print(f"Error loading context: {e}")

    communicator = TwilioCommunicator(websocket)
    if active_engine == "mistral":
        await mistral_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator)
    else:
        await gemini_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator)

async def mistral_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator):
    """Orchestrates Deepgram (STT), Mistral (LLM), and ElevenLabs (TTS)."""
    
    # Mistral Tool Schemas
    mistral_tools = [
        {
            "type": "function",
            "function": {
                "name": "check_inventory",
                "description": "Check stock and price for a product.",
                "parameters": {
                    "type": "object",
                    "properties": {"product_name": {"type": "string"}},
                    "required": ["product_name"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "query_knowledge_base",
                "description": "Search company policies and product info.",
                "parameters": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "update_lead_tool",
                "description": "Update lead status and notes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "phone": {"type": "string"},
                        "notes": {"type": "string"},
                        "status": {"type": "string"}
                    }
                }
            }
        }
    ]

    messages = [{"role": "system", "content": dynamic_instruction}]

    async def speak(text):
        """Streaming TTS from ElevenLabs to Twilio."""
        if not text.strip(): return
        
        # Clean Markdown
        clean_text = text.replace("*", "").replace("#", "").strip()
        
        url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_16000"
        print(f"Connecting to ElevenLabs TTS (PCM 16k) using Voice: {ELEVENLABS_VOICE_ID}... Text len: {len(clean_text)}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(url) as el_ws:
                    print("ElevenLabs WebSocket Connected.")
                    
                    # Bos with API Key
                    # NOTE: Some ElevenLabs models/regions strictly require the key in header or body.
                    # This body-based approach is standard for the /stream-input endpoint.
                    await el_ws.send_json({
                        "text": " ", 
                        "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                        "xi_api_key": ELEVENLABS_API_KEY
                    })
                    
                    # Send text
                    print(f"Sending text to ElevenLabs: {clean_text[:30]}...")
                    await el_ws.send_json({"text": clean_text, "try_trigger_generation": True})
                    await el_ws.send_json({"text": ""}) # EOS

                    async for message in el_ws:
                        # Log message type for deep debugging
                        # print(f"ElevenLabs Msg Type: {message.type}")
                        
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(message.data)
                            
                            if data.get("audio"):
                                print(f"Received Audio Chunk ({len(data['audio'])} base64 chars)")
                                # Decode raw PCM 16k Base64
                                pcm_16k = base64.b64decode(data["audio"])
                                
                                # Resample 16000 -> 8000
                                # width=2 (16-bit), nchannels=1
                                pcm_8k, _ = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)
                                
                                # Convert PCM 16-bit -> u-law 8-bit
                                ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                
                                # Encode back to base64 for Twilio
                                payload = base64.b64encode(ulaw_8k).decode("utf-8")
                                
                                if payload:
                                    await communicator.send_media(payload)
                            
                            if data.get("isFinal"):
                                print("ElevenLabs isFinal received.")
                                # Important: Don't break if we expect more audio, but for /stream-input it usually means done.
                                break
                            
                            if "error" in data or "message" in data:
                                print(f"ElevenLabs API Message: {data}")

                        elif message.type == aiohttp.WSMsgType.CLOSED:
                            break
                        elif message.type == aiohttp.WSMsgType.ERROR:
                            break
        except WebSocketDisconnect:
            print("Twilio WebSocket disconnected (Client hung up).")
        except Exception as e:
            if "ConnectionClosed" in str(e):
                print("Connection closed during TTS playback.")
            else:
                print(f"ElevenLabs Exception in speak(): {e}")

    async def process_mistral(user_input):
        print(f"Processing Mistral Input: {user_input}")
        messages.append({"role": "user", "content": user_input})
        try:
            print("Sending request to Mistral...")
            response = await mistral_client.chat.complete_async(
                model="mistral-large-latest",
                messages=messages,
                tools=mistral_tools
            )
            print("Mistral response received.")
            
            choice = response.choices[0].message
            if choice.tool_calls:
                # UX Improvement: Provide immediate feedback while tools run.
                # Use asyncio.create_task so it starts immediately without blocking the tool result fetching.
                filler_msg = "One moment, let me check the stock for you..."
                asyncio.create_task(speak(filler_msg))
                
                # Mistral requires the assistant message containing tool_calls 
                # to be in the history BEFORE the tool results.
                messages.append(choice)
                
                for tc in choice.tool_calls:
                    args = json.loads(tc.function.arguments)
                    print(f"Tool Triggered: {tc.function.name}({args})")
                    result = await run_tool(tc.function.name, args, transcript_accumulator, interaction_id)
                    messages.append({
                        "role": "tool",
                        "name": tc.function.name,
                        "content": str(result),
                        "tool_call_id": tc.id
                    })
                
                print("Sending tool results back to Mistral...")
                final_response = await mistral_client.chat.complete_async(
                    model="mistral-large-latest",
                    messages=messages
                )
                choice = final_response.choices[0].message

            if choice.content:
                print(f"Mistral Reply: {choice.content}")
                messages.append({"role": "assistant", "content": choice.content})
                transcript_accumulator.append(f"Rio: {choice.content}")
                save_transcript(interaction_id, transcript_accumulator)
                await speak(choice.content)
            else:
                print("Mistral returned empty content.")
        except Exception as e:
            print(f"Mistral API Error detailed: {e}")
            import traceback
            traceback.print_exc()

    # Deepgram Callback Bridge
    loop = asyncio.get_event_loop()

    def on_message(self, result, **kwargs):
        # Deepgram might return result as an object or a dict depending on the version
        # We'll handle both defensively if possible, but standard v5 is object access
        try:
            sentence = result.channel.alternatives[0].transcript
            if sentence.strip() and result.is_final:
                print(f"User (Deepgram): {sentence}")
                transcript_accumulator.append(f"User: {sentence}")
                save_transcript(interaction_id, transcript_accumulator)
                loop.create_task(process_mistral(sentence))
        except Exception as e:
            print(f"Deepgram Parse Error: {e}")
    # --- DEEPGRAM RAW WEBSOCKET IMPLEMENTATION ---
    # Bypassing the SDK completely to avoid version conflicts
    
    # WebSocket URL for Deepgram (Mulaw 8kHz matches Twilio)
    dg_url = f"wss://api.deepgram.com/v1/listen?model=nova-2&encoding=mulaw&sample_rate=8000"
    headers = {
        "Authorization": f"Token {DEEPGRAM_API_KEY}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(dg_url, headers=headers) as dg_ws:
            
            async def sender():
                nonlocal interaction_id
                try:
                    async for data in communicator.receive():
                        if data["event"] == "start":
                            if isinstance(communicator, TwilioCommunicator):
                                communicator.stream_sid = data["start"]["streamSid"]
                                if not interaction_id: interaction_id = data["start"].get("customParameters", {}).get("interaction_id")
                            print(f"Deepgram Sender: Stream Started | Interaction: {interaction_id}")
                        elif data["event"] == "media":
                            media_payload = data["media"]["payload"]
                            raw_audio = base64.b64decode(media_payload)
                            await dg_ws.send_bytes(raw_audio)
                        elif data["event"] == "stop":
                            await dg_ws.send_bytes(b"") # Close signal
                            break
                except Exception as e:
                    print(f"Telephony Receiver Error: {e}")
                finally:
                    await dg_ws.close()

            async def receiver():
                try:
                    async for msg in dg_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            res = json.loads(msg.data)
                            if "channel" in res:
                                alt = res["channel"]["alternatives"][0]
                                if alt["transcript"] and res["is_final"]:
                                    transcript = alt["transcript"]
                                    print(f"User (Deepgram Raw): {transcript}")
                                    transcript_accumulator.append(f"User: {transcript}")
                                    save_transcript(interaction_id, transcript_accumulator)
                                    await process_mistral(transcript)
                        elif msg.type == aiohttp.WSMsgType.CLOSED:
                            break
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            print(f"Deepgram WS Error")
                            break
                except Exception as e:
                    print(f"Deepgram Receiver Error: {e}")

            await asyncio.gather(sender(), receiver())
    
    print("Mistral pipeline closed.")

if __name__ == "__main__":
    import uvicorn
    # Twilio does not support WebSocket Ping/Pong, so we must disable it in Uvicorn
    # to prevent "keepalive ping timeout" errors.
    uvicorn.run(app, host="0.0.0.0", port=PORT, ws_ping_interval=None, ws_ping_timeout=None, timeout_keep_alive=60)
