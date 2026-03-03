import sys
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, get_session, engine
from models.models import SystemSettings, Interaction, Lead, Product, User
from utils.logger import setup_logger
from rag_service import sync_products_to_chroma
from utils.config import PORT
from routes import auth, crm, telephony
from communicators import TwilioCommunicator, ExotelCommunicator, EnableXCommunicator
from pipelines.voice_pipeline import VoicePipeline

# Setup logger
logger = setup_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup logic
    init_db()
    logger.info("✓ Database initialized")
    
    # Sync products on startup
    with Session(engine) as session:
        products = session.exec(select(Product)).all()
        sync_products_to_chroma(products)
    
    yield

app = FastAPI(lifespan=lifespan)

# Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(auth.router)
app.include_router(crm.router)
app.include_router(telephony.router)

# Serve uploads
import os
uploads_path = os.path.join(os.getcwd(), "uploads")
if not os.path.exists(uploads_path):
    os.makedirs(uploads_path, exist_ok=True)
app.mount("/uploads", StaticFiles(directory=uploads_path), name="uploads")

@app.get("/")
async def index():
    return {"message": "Rio CRM Voice API is running"}

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket, session: Session = Depends(get_session)):
    """Unified media-stream handler using VoicePipeline."""
    await websocket.accept()
    
    # Robust Interaction ID parsing
    interaction_id = websocket.query_params.get("interaction_id")
    if not interaction_id or interaction_id == "None":
        interaction_id = f"session_{uuid.uuid4().hex[:8]}"
        logger.info(f"Assigning fallback Interaction ID: {interaction_id}")
    
    # Load dynamic context
    settings_list = session.exec(select(SystemSettings)).all()
    all_settings = {s.key: s.value for s in settings_list}
    
    # Fetch admin user for company name
    admin_user = session.exec(select(User).where(User.id == 1)).first() or session.exec(select(User)).first()
    if admin_user:
        logger.info(f"👤 Found User for Branding: {admin_user.username} (ID: {admin_user.id}) | Company: {admin_user.company_name}")
    else:
        logger.warning("⚠️ No users found in database for branding!")

    company_name = admin_user.company_name if admin_user and admin_user.company_name else "Rio CRM"
    
    system_prompt = all_settings.get("system_instruction", "You are a helpful assistant.")
    logger.info(f"📜 Original System Prompt (first 50 chars): {system_prompt[:50]}...")

    # Inject dynamic company name into system prompt if not already present
    placeholders = ["{company_name}", "Yexis Electronics (Chennai)", "Yexis Electronics", "Rio CRM"]
    replaced = False
    for ph in placeholders:
        if ph in system_prompt:
            system_prompt = system_prompt.replace(ph, company_name)
            logger.info(f"✅ Replaced placeholder '{ph}' with '{company_name}' in prompt.")
            replaced = True
            break
    if not replaced:
        logger.warning("⚠️ No matching placeholders found in system prompt for branding.")
        
    voice_engine = all_settings.get("voice_engine", "mistral-cartesia")
    
    # 1. Instantiate Communicator (Defaulting to Twilio for /media-stream)
    communicator = TwilioCommunicator(websocket)
    
    # 2. Setup Voice Pipeline
    transcript_accumulator = []
    pipeline = VoicePipeline(
        communicator, 
        interaction_id, 
        system_prompt, 
        transcript_accumulator, 
        session,
        company_name=company_name
    )
    
    # 3. Handle specific telephony stream sid if present
    # pipeline.setup_sid(...) 

    logger.info(f"📞 Twilio connection established | Interaction: {interaction_id} | Engine: {voice_engine} | Company: {company_name}")
    
    try:
        await pipeline.run(engine_type=voice_engine)
    except Exception as e:
        logger.error(f"❌ Pipeline Error: {e}")
    finally:
        logger.info(f"👋 Pipeline finished for session: {interaction_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)