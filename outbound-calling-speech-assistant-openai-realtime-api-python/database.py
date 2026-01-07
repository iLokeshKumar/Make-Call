import os
from sqlmodel import SQLModel, create_engine, Session, Field, select
from typing import Optional, List, Generator
from datetime import datetime

# Fallback to SQLite if DATABASE_URL is not set
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crm.db")

# Attempt to use PostgreSQL if configured, otherwise SQLite
if "postgresql" in DATABASE_URL:
    try:
        engine = create_engine(DATABASE_URL)
    except Exception as e:
        print(f"Warning: Could not connect to PostgreSQL ({e}). Falling back to SQLite.")
        DATABASE_URL = "sqlite:///./crm.db"
        engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Lead(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    phone: str = Field(unique=True, index=True)
    email: Optional[str] = None
    status: str = Field(default="New")
    notes: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

class LeadCreate(SQLModel):
    name: str
    phone: str
    email: Optional[str] = None
    status: Optional[str] = "New"
    notes: Optional[str] = None

class Interaction(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int
    type: str  # "call", "sms"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)

def init_db():
    SQLModel.metadata.create_all(engine)
    # Seed Data
    with Session(engine) as session:
        if not session.exec(select(Lead)).first():
            seeds = [
                Lead(name="Alice Johnson", phone="+15550101", email="alice@example.com", status="New", notes="Interested in 55 TV"),
                Lead(name="Bob Smith", phone="+15550102", email="bob@example.com", status="Follow-up", notes="Budget $500"),
                Lead(name="Charlie Brown", phone="+918148749703", email="charlie@example.com", status="New", notes="Test Lead")
            ]
            for lead in seeds:
                session.add(lead)
            session.commit()
            print("Database initialized with seed data.")

def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
