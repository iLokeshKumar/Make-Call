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
            default_instruction = """You are Rio, a professional AI sales assistant for Yexis Electronics (Chennai).
Your goal is to identify leads, answer product queries, and book demos.

CORE CAPABILITIES & TOOLS:
- Use `get_or_create_lead` to identify the caller (Name, Phone, Email).
- Use `lookup_product` for any price or stock queries about Samsung TVs, S24, or HVAC.
- Use `book_meeting` to schedule demos on the calendar.
- Use `send_followup_email` to send information to leads.
- Use `handoff_to_human` if things get too complex for AI.

RULES:
1. Be professional and helpful.
2. If the user gives you their email or phone, make sure to update their lead info using `get_or_create_lead`.
3. Don't hallucinate tools; use exactly what you have bound."""
            session.add(SystemSettings(key="system_instruction", value=default_instruction))

        # Seed AI Verbosity if empty (1: Ultra-Concise, 2: Balanced, 3: Detailed)
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first():
            session.add(SystemSettings(key="ai_verbosity", value="2"))
        
        # Seed Voice Engine if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "llm_provider")).first():
            session.add(SystemSettings(key="llm_provider", value="mistral"))
        
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "llm_model")).first():
            session.add(SystemSettings(key="llm_model", value="mistral-small-latest"))

        if not session.exec(select(SystemSettings).where(SystemSettings.key == "tts_model")).first():
            session.add(SystemSettings(key="tts_model", value="aura-asteria-en"))

        # Seed Telephony Engine if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first():
            session.add(SystemSettings(key="telephony_engine", value="twilio"))
        
        # Seed AI Verbosity if empty (1: Ultra-Concise, 2: Balanced, 3: Detailed)
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first():
            session.add(SystemSettings(key="ai_verbosity", value="2"))

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