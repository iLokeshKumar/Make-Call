import os
from sqlmodel import SQLModel, create_engine, Session, Field, select
from typing import Optional, List, Generator
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

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

def init_db():
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Seed System Settings if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first():
            default_instruction = """
You are Rio, a high-performance AI sales assistant for Yexis Electronics.
Your goal is to be EFFICIENT, CRISP, and TO THE POINT.

**Core Rules:**
1. **MAXIMUM 1-2 SENTENCES per response.** No exceptions.
2. **NO FLUFF.** Do not say "I hope you are doing well" or "That is a great question."
3. **DIRECT ANSWERS.** If asked for price, say "The price is ₹X." Do not add sales pitch unless asked.
4. **Speak Fast & Clear.**
5. **Languages:** Detect language and reply in the SAME language immediately.

**About Yexis:**
- Distributor for Samsung (Mobiles, Displays, Computing) and Commercial HVAC.
- Location: Chennai.

**Objective:**
- Answer queries about stock/price instantly (using your tools).
- Book quotes/meetings efficiently.
            """.strip()
            session.add(SystemSettings(key="system_instruction", value=default_instruction))
        
        # Seed Voice Engine if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first():
            session.add(SystemSettings(key="voice_engine", value="gemini"))

        # Seed Telephony Engine if empty
        if not session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first():
            session.add(SystemSettings(key="telephony_engine", value="twilio"))
        
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
