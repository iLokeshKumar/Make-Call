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



class AuditMixin(SQLModel):
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), sa_column_kwargs={"onupdate": lambda: datetime.now(timezone.utc)})
    created_by: str = Field(default="System")
    updated_by: Optional[str] = Field(default=None)

class Lead(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(unique=True, index=True)
    email: Optional[str] = None
    status: str = Field(default="New")
    source: str = Field(default="Manual") 
    notes: Optional[str] = None
    enrichment_status: Optional[str] = Field(default="Not Enriched") # e.g. "Apollo Enriched", "Lusha Enriched"
    # created_at handled by mixin

class LeadCreate(SQLModel):
    name: str
    phone: str
    email: Optional[str] = None
    status: Optional[str] = "New"
    notes: Optional[str] = None

class Interaction(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int
    type: str  
    content: str
    transcript: Optional[str] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc)) # Keep for specific event time
    # created_at/updated_at/by handled by mixin

class Product(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True)
    stock: int = Field(default=0)
    price: str
    note: Optional[str] = None

class SystemSettings(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value: str

class Appointment(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(index=True)
    appointment_time: datetime
    status: str = Field(default="Scheduled") # Scheduled, Completed, Cancelled
    notes: Optional[str] = None
    meeting_link: Optional[str] = None
    calendar_event_id: Optional[str] = None

class Outcome(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(index=True)
    type: str  # e.g. "DEMO_BOOKED", "EMAIL_SENT"
    stage: str = Field(default="Interest") # Interest, Qualification, Closed
    potential_value: float = Field(default=0.0)
    probability: float = Field(default=0.0) # 0.0 to 1.0
    notes: Optional[str] = None

class User(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="sales_rep") # admin or sales_rep
    mfa_secret: Optional[str] = None
    mfa_enabled: bool = Field(default=False)
    is_active: bool = Field(default=True)
    email_verified: bool = Field(default=False)
    verification_token: Optional[str] = None
    mfa_disable_otp: Optional[str] = None

class UserCreate(SQLModel):
    username: str
    email: str
    password: str
    role: Optional[str] = "sales_rep"

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