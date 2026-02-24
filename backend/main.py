import sys
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import Session, select

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, get_session, engine
from models.models import SystemSettings, Interaction, Lead
from utils.logger import setup_logger
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
    settings = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    system_prompt = settings.value if settings else "You are a helpful assistant."
    
    # 1. Instantiate Communicator (Defaulting to Twilio for /media-stream)
    communicator = TwilioCommunicator(websocket)
    
    # 2. Setup Voice Pipeline
    transcript_accumulator = []
    pipeline = VoicePipeline(communicator, interaction_id, system_prompt, transcript_accumulator)
    
    # 3. Handle specific telephony stream sid if present
    # pipeline.setup_sid(...) 

    logger.info(f"📞 Twilio connection established | Interaction: {interaction_id}")
    
    try:
        await pipeline.run()
    except Exception as e:
        logger.error(f"❌ Pipeline Error: {e}")
    finally:
        logger.info(f"👋 Pipeline finished for session: {interaction_id}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)