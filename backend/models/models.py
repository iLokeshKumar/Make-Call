from sqlmodel import SQLModel, Field, select
from typing import Optional, List
from datetime import datetime, timezone

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
    enrichment_status: Optional[str] = Field(default="Not Enriched")

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
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

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
    status: str = Field(default="Scheduled")
    notes: Optional[str] = None
    meeting_link: Optional[str] = None
    calendar_event_id: Optional[str] = None

class Outcome(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    lead_id: int = Field(index=True)
    type: str
    stage: str = Field(default="Interest")
    potential_value: float = Field(default=0.0)
    probability: float = Field(default=0.0)
    notes: Optional[str] = None

class LatencyLog(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    interaction_id: Optional[int] = Field(default=None, index=True)
    engine: str
    stt_ms: float = Field(default=0.0)
    llm_ms: float = Field(default=0.0)
    tts_ms: float = Field(default=0.0)
    total_ms: float = Field(default=0.0)
    
    stt_provider: Optional[str] = None
    stt_model: Optional[str] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    tts_provider: Optional[str] = None
    tts_model: Optional[str] = None
    
    notes: Optional[str] = None

class User(AuditMixin, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    username: str = Field(unique=True, index=True)
    email: str = Field(unique=True, index=True)
    hashed_password: str
    role: str = Field(default="sales_rep")
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

class Token(SQLModel):
    access_token: str
    token_type: str

class TokenData(SQLModel):
    username: Optional[str] = None

class ApolloSearch(SQLModel):
    keywords: str

class MFAVerify(SQLModel):
    token: str

class MFADisableRequest(SQLModel):
    token: str

class ResendVerification(SQLModel):
    email: Optional[str] = None
    username: Optional[str] = None
