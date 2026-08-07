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
import logging
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
logger = logging.getLogger(__name__)


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


@router.get("/google-sheets/tabs")
async def list_google_sheet_tabs(
    url: str = Query(..., description="Public Google Sheet URL"),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Return worksheet tabs for a public Google Sheet so the user can choose one."""
    del current_user
    import httpx as _httpx
    from services.inventory.google_sheets_provider import _extract_sheet_id, list_public_worksheets

    sheet_id = _extract_sheet_id(url)
    if not sheet_id:
        raise HTTPException(status_code=400, detail="Please paste a valid Google Sheets URL.")
    try:
        tabs = await list_public_worksheets(url)
    except Exception as exc:
        logger.warning("[inventory_sources] google sheet tab discovery failed sheet=%s error=%s", sheet_id, exc)
        raise HTTPException(
            status_code=422,
            detail="Could not read worksheet tabs. Check that sharing is set to Anyone with the link can view.",
        ) from exc

    if not tabs:
        # HTML parsing found nothing — verify the sheet is accessible by probing the CSV export.
        # If reachable, return a single default tab so the UI can auto-select it.
        try:
            probe_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
            async with _httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
                probe = await client.get(probe_url)
            if probe.status_code == 200 and probe.content:
                tabs = [{"name": "Sheet 1", "gid": "0"}]
                logger.info(
                    "[inventory_sources] tab discovery found 0 tabs; sheet accessible — returning default tab sheet_id=%s",
                    sheet_id,
                )
        except Exception as probe_exc:
            logger.info("[inventory_sources] probe failed sheet_id=%s error=%s", sheet_id, probe_exc)

    if not tabs:
        raise HTTPException(
            status_code=422,
            detail="Could not read worksheet tabs. Check that sharing is set to Anyone with the link can view.",
        )

    return {"sheet_id": sheet_id, "tabs": tabs}


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
    logger.info(
        "[inventory_sources] created id=%s company=%s name=%r type=%s priority=%s enabled=%s config_keys=%s",
        source.id,
        source.company_id,
        source.name,
        source.source_type,
        source.priority,
        source.enabled,
        sorted((source.config_json or {}).keys()),
    )
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
    logger.info(
        "[inventory_sources] updated id=%s company=%s name=%r type=%s priority=%s enabled=%s config_keys=%s",
        source.id,
        source.company_id,
        source.name,
        source.source_type,
        source.priority,
        source.enabled,
        sorted((source.config_json or {}).keys()),
    )
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
    """Trigger a sync — for Google Sheets invalidates the in-memory cache so
    the next lookup re-fetches fresh data from the sheet."""
    source = _get_source(session, current_user.company_id, source_id)

    if source.source_type == "google_sheets":
        from services.inventory.google_sheets_provider import GoogleSheetsProvider, invalidate
        tmp = GoogleSheetsProvider(config=source.config_json, priority=source.priority)
        invalidate(tmp._cache_key)
        logger.info(
            "[inventory_sources] sync invalidated google_sheets cache source_id=%s cache_key=%s",
            source.id,
            tmp._cache_key,
        )

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
