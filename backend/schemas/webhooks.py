from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class WebhookConfigBase(BaseModel):
    name: str
    url: str
    events: List[str]
    secret: Optional[str] = None
    is_active: bool = True
    timeout_seconds: int = 10
    agent_filter: Optional[str] = None
    outcome_filter: Optional[str] = None

class WebhookConfigCreate(WebhookConfigBase):
    pass

class WebhookConfigUpsert(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    secret: Optional[str] = None
    is_active: Optional[bool] = None
    timeout_seconds: Optional[int] = None
    agent_filter: Optional[str] = None
    outcome_filter: Optional[str] = None

class WebhookConfigRead(WebhookConfigBase):
    id: int
    company_id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

class WebhookDeliveryLogRead(BaseModel):
    id: int
    company_id: int
    webhook_id: int
    event_type: str
    payload_hash: str
    http_status: Optional[int]
    response_ms: Optional[int]
    error: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}