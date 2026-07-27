from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MCPServer(SQLModel, table=True):
    """Persisted registry of external MCP servers, one row per configured connection."""
    __tablename__ = "mcp_servers"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    provider: str = Field(max_length=50)        # apollo | zoho | custom
    url: str = Field(max_length=500)
    transport: str = Field(default="http", max_length=20)   # http | sse | stdio
    auth_type: str = Field(default="oauth2", max_length=20) # oauth2 | api_key | none
    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    capabilities_json: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    enabled: bool = Field(default=True)
    priority: int = Field(default=100)
    last_health_status: Optional[str] = Field(default=None, max_length=20)
    last_health_checked_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


class MCPToolCache(SQLModel, table=True):
    """Cached tool metadata discovered from an MCPServer, refreshed on demand."""
    __tablename__ = "mcp_tool_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    server_id: int = Field(foreign_key="mcp_servers.id", index=True)
    tool_name: str = Field(max_length=200)
    description: Optional[str] = Field(default=None)
    input_schema_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    cached_at: datetime = Field(default_factory=_utc_now)


# ── Request/Response schemas ─────────────────────────────────────────────────── #

class MCPServerCreate(SQLModel):
    name: str
    provider: str
    url: str
    transport: str = "http"
    auth_type: str = "oauth2"
    config_json: dict = {}
    capabilities_json: list = []
    enabled: bool = True
    priority: int = 100


class MCPServerUpdate(SQLModel):
    name: Optional[str] = None
    url: Optional[str] = None
    transport: Optional[str] = None
    auth_type: Optional[str] = None
    config_json: Optional[dict] = None
    capabilities_json: Optional[list] = None
    enabled: Optional[bool] = None
    priority: Optional[int] = None


class MCPServerRead(SQLModel):
    id: int
    company_id: int
    name: str
    provider: str
    url: str
    transport: str
    auth_type: str
    capabilities_json: list
    enabled: bool
    priority: int
    last_health_status: Optional[str]
    last_health_checked_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class MCPToolCacheRead(SQLModel):
    id: int
    server_id: int
    tool_name: str
    description: Optional[str]
    cached_at: datetime
