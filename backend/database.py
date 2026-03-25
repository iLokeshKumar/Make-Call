import os
from sqlmodel import SQLModel, create_engine, Session, Field, select
from typing import Optional, List, Generator
from datetime import datetime, timezone
from dotenv import load_dotenv

# Find .env in the same directory as this file
current_dir = os.path.dirname(os.path.abspath(__file__))
env_path = os.path.join(current_dir, ".env")
load_dotenv(env_path)

# Fallback to SQLite if DATABASE_URL is not set
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crm.db")

# Attempt to use PostgreSQL if configured, otherwise SQLite
if "postgresql" in DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL, echo=True) # echo=True prints SQL to console for proof
        # Test connection
        with engine.connect() as conn:
            pass
        print("Connected to PostgreSQL successfully.")
    except Exception as e:
        print(f"Warning: Could not connect to PostgreSQL: {e}")
        print("Falling back to SQLite (crm.db).")
        DATABASE_URL = "sqlite:///./crm.db"
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=True)
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False}, echo=True)

from models.models import (
    Lead, Interaction, Product, SystemSettings, Appointment, 
    Outcome, LatencyLog, User, AuditMixin, LeadCreate, UserCreate,
    Token, TokenData, ApolloSearch, MFAVerify, MFADisableRequest, ResendVerification
)

def init_db():
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Seed System Settings if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first():
            default_instruction = """You are Rio, a professional Digital Sales Representative for {company_name}.
Your goal is to identify leads, answer product queries, and book demos.

CORE CAPABILITIES & TOOLS:
- Use `get_or_create_lead` to identify the caller (Name, Phone, Email). Use this towards the end of a conversation (e.g., when close to booking or finishing) to identify the user. Avoid calling this at the very start of the call.
- Use `get_product_info` for any price or stock queries about Samsung TVs, S24, or HVAC.
- Use `book_meeting` to schedule demos on the calendar.
- Use `send_followup_email` to send information to leads.
- Use `handoff_to_human` if things get too complex for AI.

RULES:
1. Be personal, helpful, and speak like a human representative named Rio.
2. Only collect contact details and call `get_or_create_lead` towards the end of the call or when the user is ready to book.
3. CRITICAL: Never speak technical syntax, tool names, JSON code, colons, or internal IDs. Speak in plain, conversational language only.
4. Don't hallucinate tools; use exactly what you have bound.
"""
            session.add(SystemSettings(key="system_instruction", value=default_instruction))
            

        # Seed AI Verbosity if empty (1: Ultra-Concise, 2: Balanced, 3: Detailed)
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first():
            session.add(SystemSettings(key="ai_verbosity", value="1"))
        
        # Seed Voice Engine if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "llm_provider")).first():
            session.add(SystemSettings(key="llm_provider", value="mistral"))
        
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "llm_model")).first():
            session.add(SystemSettings(key="llm_model", value="mistral-small-latest"))

        if not session.exec(select(SystemSettings).where(SystemSettings.key == "tts_model")).first():
            session.add(SystemSettings(key="tts_model", value="aura-asteria-en"))

        # Seed LLM model defaults (global, user_id=None)
        _model_defaults = [
            #("MISTRAL_MODEL",    "mistral-small-latest"),
            #("CEREBRAS_MODEL",   "gpt-oss-120b"),
            #("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            #("GEMINI_MODEL",     "gemini-2.0-flash"),
            #("OPENAI_MODEL",     "gpt-4o-mini"),
        ]
        for key, default_val in _model_defaults:
            if not session.exec(select(SystemSettings).where(SystemSettings.key == key, SystemSettings.user_id == None)).first():
                session.add(SystemSettings(key=key, value=default_val))

        # Seed voice ID / STT model defaults (global, user_id=None)
        _voice_defaults = [
            #("CARTESIA_VOICE_ID",   "a0e99841-438c-4a64-b679-ae501e7d6091"),
            #("ELEVENLABS_VOICE_ID", "CwhOLp6mAE7h9asvUURR"),
            #("DEEPGRAM_VOICE",      "aura-asteria-en"),
            #("DEEPGRAM_STT_MODEL",  "nova-2"),
            #("DEEPGRAM_TTS_MODEL",  "aura-asteria-en"),
            #("CARTESIA_STT_MODEL",  "ink-whisper"),
            #("ELEVENLABS_TTS_MODEL", "eleven_turbo_v2_5"),
            #("ELEVENLABS_STT_MODEL", "scribe_v1"),
            #("MIMO_VOICE_ID", "CwhOLp6mAE7h9asvUURR"),
            #("MIMO_TTS_MODEL", "mimo_turbo_v2_5"),
            #("MIMO_MODEL", "mimo-v2-pro"),
        ]
        for key, default_val in _voice_defaults:
            if not session.exec(select(SystemSettings).where(SystemSettings.key == key, SystemSettings.user_id == None)).first():
                session.add(SystemSettings(key=key, value=default_val))

        # Seed Telephony Engine if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first():
            session.add(SystemSettings(key="telephony_engine", value="twilio"))
        
        # Seed AI Verbosity if empty (1: Ultra-Concise, 2: Balanced, 3: Detailed)
        # if not session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first():
        #     session.add(SystemSettings(key="ai_verbosity", value="2"))

        # Seed Products if empty
        if not session.exec(select(Product)).first():
            default_products = [
                Product(name="Samsung 55 TV", stock=5, price="₹65,000"),
                Product(name="Samsung S24", stock=12, price="₹75,000"),
                Product(name="Galaxy Watch", stock=0, price="₹25,000"),
                Product(name="VRF System", stock=2, price="₹4,00,000", note="Requires installation team")
            ]
            for p in default_products:
                session.add(p)
        
        session.commit()
    
    print("Database initialized.")

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session