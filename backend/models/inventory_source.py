from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InventorySource(SQLModel, table=True):
    """Pluggable inventory data source configuration. The built-in 'db_product' source
    wraps the existing Product table; additional rows enable CSV, Sheets, ERP API."""
    __tablename__ = "inventory_sources"

    id: Optional[int] = Field(default=None, primary_key=True)
    company_id: int = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=200)
    source_type: str = Field(max_length=50)  # db_product | csv | google_sheets | erp_api | manual
    priority: int = Field(default=100)
    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    enabled: bool = Field(default=True)
    last_sync_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


# ── Request/Response schemas ─────────────────────────────────────────────────── #

class InventorySourceCreate(SQLModel):
    name: str
    source_type: str
    priority: int = 100
    config_json: dict = {}
    enabled: bool = True


class InventorySourceUpdate(SQLModel):
    name: Optional[str] = None
    source_type: Optional[str] = None
    priority: Optional[int] = None
    config_json: Optional[dict] = None
    enabled: Optional[bool] = None


class InventorySourceRead(SQLModel):
    id: int
    company_id: int
    name: str
    source_type: str
    priority: int
    config_json: dict
    enabled: bool
    last_sync_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
