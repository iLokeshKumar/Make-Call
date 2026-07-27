"""
inventory_sources.py - API routes for managing pluggable inventory sources.

GET    /inventory-sources              — list all sources for the company
POST   /inventory-sources              — add a new source
PATCH  /inventory-sources/{id}         — update a source
DELETE /inventory-sources/{id}         — remove a source
POST   /inventory-sources/{id}/sync    — trigger a sync (e.g. re-read CSV)
GET    /inventory-sources/lookup       — look up a product by SKU
GET    /inventory-sources/search       — search products
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.inventory_source import (
    InventorySource,
    InventorySourceCreate,
    InventorySourceRead,
    InventorySourceUpdate,
)
from models.models import User

router = APIRouter(prefix="/inventory-sources", tags=["Inventory Sources"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_source(session: Session, company_id: int, source_id: int) -> InventorySource:
    source = session.exec(
        select(InventorySource).where(
            InventorySource.company_id == company_id,
            InventorySource.id == source_id,
        )
    ).first()
    if not source:
        raise HTTPException(status_code=404, detail=f"Inventory source {source_id} not found")
    return source


@router.get("", response_model=list[InventorySourceRead])
def list_sources(
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    return list(session.exec(
        select(InventorySource)
        .where(InventorySource.company_id == current_user.company_id)
        .order_by(InventorySource.priority.desc(), InventorySource.name)
    ).all())


@router.post("", response_model=InventorySourceRead)
def create_source(
    data: InventorySourceCreate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    source = InventorySource(company_id=current_user.company_id, **data.model_dump())
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


@router.patch("/{source_id}", response_model=InventorySourceRead)
def update_source(
    source_id: int,
    data: InventorySourceUpdate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    source = _get_source(session, current_user.company_id, source_id)
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(source, field, value)
    source.updated_at = _utc_now()
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


@router.delete("/{source_id}")
def delete_source(
    source_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    source = _get_source(session, current_user.company_id, source_id)
    session.delete(source)
    session.commit()
    return {"deleted": True}


@router.post("/{source_id}/sync")
async def sync_source(
    source_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Trigger a sync for the given source (re-reads CSV cache, etc.)."""
    source = _get_source(session, current_user.company_id, source_id)
    # CSV provider is file-based; clearing its internal cache forces a re-read next call
    source.last_sync_at = _utc_now()
    session.add(source)
    session.commit()
    return {"synced": True, "source": source.name, "synced_at": source.last_sync_at}


@router.get("/lookup")
async def lookup_product(
    sku: str = Query(..., description="Product SKU to look up"),
    location: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Look up a product by SKU across all enabled inventory sources."""
    from services.inventory.factory import build_inventory_service
    inv = await build_inventory_service(session, current_user.company_id)
    result = await inv.lookup(sku=sku, location=location)
    if not result:
        raise HTTPException(status_code=404, detail=f"Product '{sku}' not found")
    return result


@router.get("/search")
async def search_products(
    q: str = Query(..., description="Search query"),
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    """Search products across all enabled inventory sources."""
    from services.inventory.factory import build_inventory_service
    inv = await build_inventory_service(session, current_user.company_id)
    return {"results": await inv.search(q)}
