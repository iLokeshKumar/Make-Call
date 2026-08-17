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
import time
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


def _spreadsheet_source_type(source_type: str, config: dict[str, Any] | None) -> str:
    """Store the provider-specific type for spreadsheet URLs."""
    if source_type not in {"google_sheets", "microsoft_excel", "zoho_sheet"}:
        return source_type
    from urllib.parse import urlparse
    host = urlparse(str((config or {}).get("url") or "")).netloc.lower()
    if host in {"docs.google.com", "sheets.google.com"}:
        return "google_sheets"
    if "excel.cloud.microsoft" in host or "onedrive" in host or "sharepoint" in host:
        return "microsoft_excel"
    if "zohopublic.com" in host or "sheet.zoho.com" in host:
        return "zoho_sheet"
    return source_type


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
    sources = list(session.exec(
        select(InventorySource)
        .where(InventorySource.company_id == current_user.company_id)
        .order_by(InventorySource.priority.desc(), InventorySource.name)
    ).all())
    # Older records may have stored every remote workbook as google_sheets.
    # Normalize the response so the UI shows the actual provider immediately.
    for source in sources:
        source.source_type = _spreadsheet_source_type(source.source_type, source.config_json)
    return sources


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

    # Best-effort workbook title for auto-filling the source name in the UI.
    name = None
    try:
        from services.inventory.google_sheets_provider import public_sheet_title
        name = await public_sheet_title(url)
    except Exception as exc:
        logger.info("[inventory_sources] google sheet title fetch failed sheet_id=%s error=%s", sheet_id, exc)

    return {"sheet_id": sheet_id, "tabs": tabs, "name": name}


@router.get("/spreadsheet/tabs")
async def list_remote_spreadsheet_tabs(
    url: str = Query(..., description="Zoho Sheet or Microsoft Excel URL"),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    from services.inventory.remote_spreadsheet_provider import list_remote_worksheets
    try:
        tabs, name = await list_remote_worksheets(url, session, current_user.company_id)
        return {"tabs": tabs, "name": name, "provider": "remote_spreadsheet"}
    except Exception as exc:
        logger.warning("[inventory_sources] remote spreadsheet tab discovery failed url=%s error=%s", url, exc)
        # Surface the real upstream error (e.g. Graph's error body) whenever
        # the provider raised a curated ValueError or an HTTP error with a
        # readable response. Everything else is internal (network, parse, etc.)
        # → generic advice.
        detail = ""
        if isinstance(exc, ValueError) and str(exc).strip():
            detail = str(exc).strip()
        else:
            from services.inventory.remote_spreadsheet_provider import _http_error_text
            response = getattr(exc, "response", None)
            if response is not None:
                upstream = _http_error_text(response)
                if upstream and upstream != f"HTTP {getattr(response, 'status_code', '')}":
                    detail = f"Could not read this workbook ({upstream})."
        if not detail:
            detail = (
                "Could not read this workbook. Zoho links must be public; "
                "Microsoft Excel/OneDrive requires Connect Microsoft 365."
            )
        raise HTTPException(status_code=422, detail=detail) from exc


@router.get("/google-drive/spreadsheets")
async def list_google_drive_spreadsheets(
    refresh: int = Query(0, description="Set 1 to bypass the cached listing"),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """List spreadsheets from the connected Google Workspace Drive account."""
    import httpx as _httpx
    from routes.calendar import get_company_calendar_credentials

    key = ("google_sheets", current_user.company_id)
    now = time.monotonic()
    cached = _browse_cache.get(key)
    if refresh != 1 and cached and now - cached[0] < _BROWSE_CACHE_TTL_SECONDS:
        return cached[1]

    creds = get_company_calendar_credentials(session, current_user.company_id)
    if not creds or not creds.token:
        result = {"connected": False, "spreadsheets": [], "account_email": None}
    else:
        try:
            headers = {"Authorization": f"Bearer {creds.token}"}
            url = (
                "https://www.googleapis.com/drive/v3/files?"
                "q=mimeType%3D%27application%2Fvnd.google-apps.spreadsheet%27+and+trashed%3Dfalse"
                "&fields=files%2Fid%2Cfiles%2Fname%2Cfiles%2FwebViewLink"
                "&pageSize=50&orderBy=modifiedTime+desc"
            )
            async with _httpx.AsyncClient(timeout=10) as client:
                # Which account is connected — lets the user confirm the picker
                # is looking at the right Google account (works even under the
                # restricted drive.file scope, where listing may be empty).
                account_email = None
                try:
                    about_resp = await client.get(
                        "https://www.googleapis.com/drive/v3/about",
                        params={"fields": "user(emailAddress)"},
                        headers=headers,
                    )
                    if about_resp.status_code == 200:
                        account_email = (about_resp.json().get("user") or {}).get("emailAddress")
                except Exception as exc:
                    logger.debug("[inventory_sources] Google Drive about failed: %s", exc)

                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    files = data.get("files", [])
                    spreadsheets = [
                        {
                            "id": f["id"],
                            "name": f.get("name", "Untitled Spreadsheet"),
                            "url": f.get("webViewLink") or f"https://docs.google.com/spreadsheets/d/{f['id']}/edit",
                        }
                        for f in files
                        if f.get("id")
                    ]
                    result = {"connected": True, "spreadsheets": spreadsheets, "error": None, "account_email": account_email}
                elif resp.status_code == 403 and "SERVICE_DISABLED" in resp.text:
                    logger.warning("[inventory_sources] Google Drive API is disabled in Google Cloud Console")
                    result = {
                        "connected": True,
                        "spreadsheets": [],
                        "error": "Google Drive API is disabled in Google Cloud Console. Enable Google Drive API & Google Sheets API in console.cloud.google.com to pick spreadsheets directly.",
                        "account_email": account_email,
                    }
                else:
                    logger.warning("[inventory_sources] Google Drive API returned %s: %s", resp.status_code, resp.text)
                    result = {"connected": True, "spreadsheets": [], "error": None, "account_email": account_email}
        except Exception as exc:
            logger.warning("[inventory_sources] Google Drive spreadsheets list error: %s", exc)
            result = {"connected": True, "spreadsheets": [], "error": None, "account_email": None}

    _browse_cache[key] = (now, result)
    return result


# Listing a connected account's workbooks is slow (the Microsoft drive walk
# can take ~8s). Cache the result per (provider, company) for a short TTL so
# reopening the modal doesn't re-walk the drive every time; the Refresh button
# passes refresh=1 to bypass.
_BROWSE_CACHE_TTL_SECONDS = 60
_browse_cache: dict[tuple[str, int], tuple[float, dict]] = {}


@router.get("/browse")
async def browse_connected_files(
    provider: str = Query(..., description="microsoft_excel | zoho_sheet | google_sheets"),
    refresh: int = Query(0, description="Set 1 to bypass the cached listing"),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """List spreadsheet workbooks from a connected account — no link pasting.

    The account is already authenticated via OAuth, so the user can pick a
    workbook from a dropdown instead of copying/pasting a share URL. Returns
    {"connected": bool, "files": [{id, name, url}], "error": str | None}.
    """
    provider = (provider or "").lower()
    if provider == "google_sheets":
        return await list_google_drive_spreadsheets(refresh=refresh, current_user=current_user, session=session)
    if provider not in ("microsoft_excel", "zoho_sheet"):
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider}")

    key = (provider, current_user.company_id)
    now = time.monotonic()
    cached = _browse_cache.get(key)
    if refresh != 1 and cached and now - cached[0] < _BROWSE_CACHE_TTL_SECONDS:
        return cached[1]

    if provider == "microsoft_excel":
        result = await _list_microsoft_workbooks(session, current_user.company_id)
    else:
        result = await _list_zoho_workbooks(session, current_user.company_id)
    _browse_cache[key] = (now, result)
    return result


_MS_DRIVE_SELECT = "id,name,webUrl,file,folder"


def _ms_is_spreadsheet(item: dict) -> bool:
    name = item.get("name") or ""
    mime = (item.get("file") or {}).get("mimeType") or ""
    return "spreadsheet" in mime.lower() or name.lower().endswith((".xlsx", ".xls", ".csv"))


async def _list_microsoft_workbooks(session: Session, company_id: int) -> dict:
    """List Excel workbooks from the connected Microsoft 365 OneDrive account.

    Fast path: Graph drive search (works for OneDrive for Business and
    SharePoint). Personal OneDrive accounts return 501 notSupported for the
    search function, so we fall back to walking the drive tree (root + one
    folder level), which is supported everywhere.
    """
    import httpx as _httpx
    from routes.microsoft_oauth import get_or_refresh_microsoft_token

    token = get_or_refresh_microsoft_token(session, company_id)
    if not token:
        return {"connected": False, "files": [], "error": None}

    def _auth_headers() -> dict:
        return {"Authorization": f"Bearer {token}"}

    async def _maybe_refresh(resp) -> httpx.Response:
        nonlocal token
        if resp.status_code == 401:
            fresh = get_or_refresh_microsoft_token(session, company_id, force=True)
            if fresh and fresh != token:
                token = fresh
                return resp  # caller retries with the fresh token
        return resp

    seen: dict[str, dict] = {}

    def _collect(items) -> None:
        for item in items or []:
            if not isinstance(item, dict) or item.get("folder"):
                continue
            item_id = item.get("id")
            web_url = item.get("webUrl") or ""
            if not item_id or not web_url or not _ms_is_spreadsheet(item):
                continue
            seen[item_id] = {"id": item_id, "name": item.get("name") or item_id, "url": web_url}

    async with _httpx.AsyncClient(timeout=20) as client:
        # 1) Fast path: search.
        search_ok = False
        for ext in ("xlsx", "xls", "csv"):
            try:
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me/drive/root/search",
                    headers=_auth_headers(),
                    params={"q": f".{ext}", "$select": _MS_DRIVE_SELECT, "$top": 100},
                )
                if resp.status_code == 401:
                    resp = await _maybe_refresh(resp)
                    if resp.status_code == 401:
                        continue
                    resp = await client.get(
                        "https://graph.microsoft.com/v1.0/me/drive/root/search",
                        headers=_auth_headers(),
                        params={"q": f".{ext}", "$select": _MS_DRIVE_SELECT, "$top": 100},
                    )
                if resp.status_code == 200:
                    search_ok = True
                    _collect(resp.json().get("value"))
                else:
                    logger.warning(
                        "[inventory_sources] Microsoft drive search (%s) returned %s: %s",
                        ext, resp.status_code, resp.text[:200],
                    )
            except Exception as exc:
                logger.warning("[inventory_sources] Microsoft drive search error (%s): %s", ext, exc)

        # 2) Fallback: personal OneDrive rejects search (501). Walk the drive
        #    tree — root children plus one level of folders — and collect any
        #    spreadsheets found.
        if not search_ok:
            try:
                resp = await client.get(
                    "https://graph.microsoft.com/v1.0/me/drive/root/children",
                    headers=_auth_headers(),
                    params={"$select": _MS_DRIVE_SELECT, "$top": 200},
                )
                if resp.status_code == 401:
                    resp = await _maybe_refresh(resp)
                    if resp.status_code == 401:
                        resp = None
                    else:
                        resp = await client.get(
                            "https://graph.microsoft.com/v1.0/me/drive/root/children",
                            headers=_auth_headers(),
                            params={"$select": _MS_DRIVE_SELECT, "$top": 200},
                        )
                if resp is not None and resp.status_code == 200:
                    root_items = resp.json().get("value") or []
                    folder_ids = [it["id"] for it in root_items if isinstance(it, dict) and it.get("folder") and it.get("id")]
                    _collect(root_items)
                    # One level of folders, bounded — keeps the picker fast.
                    for fid in folder_ids[:40]:
                        if len(seen) >= 100:
                            break
                        try:
                            sub = await client.get(
                                f"https://graph.microsoft.com/v1.0/me/drive/items/{fid}/children",
                                headers=_auth_headers(),
                                params={"$select": _MS_DRIVE_SELECT, "$top": 100},
                            )
                            if sub.status_code == 200:
                                _collect(sub.json().get("value"))
                        except Exception as exc:
                            logger.warning("[inventory_sources] Microsoft drive folder walk error: %s", exc)
                else:
                    logger.warning(
                        "[inventory_sources] Microsoft drive root listing returned %s",
                        getattr(resp, "status_code", None),
                    )
            except Exception as exc:
                logger.warning("[inventory_sources] Microsoft drive walk error: %s", exc)

    return {"connected": True, "files": list(seen.values()), "error": None}


async def _list_zoho_workbooks(session: Session, company_id: int) -> dict:
    """List workbooks from the connected Zoho Sheet account."""
    from services.inventory.remote_spreadsheet_provider import _zoho_sheet_api, _zoho_sheet_token

    if not _zoho_sheet_token(session, company_id):
        return {"connected": False, "files": [], "error": None}

    # The Sheet DATA API expects form-encoded bodies for method-style calls;
    # reuse the provider helper (regional hosts + 401 refresh) rather than
    # duplicating it.
    resp = await _zoho_sheet_api(
        "POST", "/api/v2/workbooks", session, company_id, {"method": "workbook.list"}
    )
    if resp is None:
        logger.warning("[inventory_sources] Zoho workbook.list failed for company=%s", company_id)
        return {"connected": True, "files": [], "error": "Zoho Sheet API is unreachable — check the Zoho connection."}
    try:
        data = resp.json()
    except Exception:
        return {"connected": True, "files": [], "error": "Zoho Sheet returned an unreadable response."}

    workbooks = data.get("workbooks") if isinstance(data, dict) else None
    files = []
    for wb in workbooks or []:
        if not isinstance(wb, dict):
            continue
        rid = wb.get("resource_id")
        if not rid:
            continue
        files.append({
            "id": str(rid),
            "name": str(wb.get("workbook_name") or rid).strip(),
            "url": f"https://workdrive.zohopublic.com/sheet/open/{rid}",
        })
    return {"connected": True, "files": files, "error": None}


@router.get("/google-drive/tabs")
async def list_google_drive_sheet_tabs(
    sheet_id: str = Query(..., description="Google Spreadsheet ID"),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """List worksheets for a spreadsheet via Google Sheets API (connected account)."""
    import httpx as _httpx
    from routes.calendar import get_company_calendar_credentials

    creds = get_company_calendar_credentials(session, current_user.company_id)
    if creds and creds.token:
        try:
            headers = {"Authorization": f"Bearer {creds.token}"}
            url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}?fields=sheets.properties(sheetId%2Ctitle)%2Cproperties.title"
            async with _httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    raw_sheets = data.get("sheets", [])
                    tabs = [
                        {
                            "name": s["properties"]["title"],
                            "gid": str(s["properties"]["sheetId"]),
                        }
                        for s in raw_sheets
                        if "properties" in s and "title" in s["properties"]
                    ]
                    if tabs:
                        return {"sheet_id": sheet_id, "tabs": tabs, "name": (data.get("properties") or {}).get("title") or None}
        except Exception as exc:
            logger.warning("[inventory_sources] Sheets API tabs fetch failed: %s", exc)

    # Fallback to public discovery if OAuth fetch failed or not connected
    from services.inventory.google_sheets_provider import list_public_worksheets, public_sheet_title
    sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    tabs = await list_public_worksheets(sheet_url)
    if not tabs:
        tabs = [{"name": "Sheet 1", "gid": "0"}]
    name = None
    try:
        name = await public_sheet_title(sheet_url)
    except Exception as exc:
        logger.info("[inventory_sources] google drive fallback title fetch failed sheet_id=%s error=%s", sheet_id, exc)
    return {"sheet_id": sheet_id, "tabs": tabs, "name": name}


@router.get("/zoho-books/test")
async def test_zoho_books_connection(
    organization_id: str = Query(..., description="Zoho Books organization ID to test"),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    """Verify the Zoho Books connection + organization ID without saving.

    Returns the item count on the first page, or a 422 with a specific,
    actionable message (not connected / bad org ID / auth scope) so the UI can
    tell the user exactly what to fix.
    """
    from services.inventory.zoho_books_provider import ZohoBooksProvider
    provider = ZohoBooksProvider(
        config={"organization_id": organization_id},
        session=session,
        company_id=current_user.company_id,
    )
    try:
        return await provider.test_connection()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("", response_model=InventorySourceRead)
def create_source(
    data: InventorySourceCreate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    payload = data.model_dump()
    payload["source_type"] = _spreadsheet_source_type(payload["source_type"], payload.get("config_json"))
    source = InventorySource(company_id=current_user.company_id, **payload)
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
    payload = data.model_dump(exclude_none=True)
    payload["source_type"] = _spreadsheet_source_type(payload.get("source_type", source.source_type), payload.get("config_json", source.config_json))
    for field, value in payload.items():
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
