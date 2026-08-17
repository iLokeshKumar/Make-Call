"""Read public Zoho Sheet and Microsoft Excel workbooks as inventory sources."""
from __future__ import annotations

import io
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

import httpx

from services.inventory.base import InventoryProvider

logger = logging.getLogger(__name__)


def _zoho_book_id(url: str) -> str | None:
    match = re.search(r"/(?:sheet/(?:open|published)|workdrive[^/]*/sheet/(?:open|published))/([^/?#]+)", url, re.I)
    return match.group(1) if match else None


def _zoho_export_urls(book_id: str, sheet_name: str | None = None) -> list[str]:
    # Public Zoho Sheet links download through the public export endpoint; it
    # selects a specific tab with ?sheetname= and returns an EMPTY body for an
    # unknown tab name, so the fallback candidate below always lands on the
    # default tab. The legacy sheet.zoho.com/api/public/csv/download and the
    # authenticated WorkDrive binary endpoints are kept as last-resort
    # fallbacks for older / WorkDrive-backed books.
    export = f"https://sheet.zohopublic.com/sheet/export/{book_id}?format=csv"
    export_with_tab = f"{export}&sheetname={quote(sheet_name)}" if sheet_name else export
    legacy_suffix = f"/sheet-name:{quote(sheet_name)}" if sheet_name else ""
    return [
        export_with_tab,
        export,
        f"https://download.zoho.com/v1/workdrive/download/{book_id}",
        f"https://download.zoho.in/v1/workdrive/download/{book_id}",
        f"https://download.zoho.eu/v1/workdrive/download/{book_id}",
        f"https://sheet.zoho.com/api/public/csv/download/{book_id}{legacy_suffix}",
        f"https://sheet.zoho.com/api/public/csv/download/{book_id}",
    ]


def _microsoft_ids(url: str) -> tuple[str, str] | None:
    query = parse_qs(urlparse(url).query)
    drive_id = (query.get("driveId") or [None])[0]
    doc_id = (query.get("docId") or [None])[0]
    if drive_id and doc_id:
        return (drive_id, doc_id)
    # OneDrive share links carry resid=DRIVEID!ITEMID (e.g. from 1drv.ms
    # short links or onedrive.live.com/:x:/g/personal/... URLs).
    resid = (query.get("resid") or [None])[0]
    if resid and "!" in resid:
        rid, iid = resid.split("!", 1)
        if rid and iid:
            return (rid, iid)
    return None


def _encode_sharing_url(url: str) -> str:
    """Encode a sharing URL for Graph's /shares endpoint.

    Microsoft requires base64url of the URL — '/'→'_', '+'→'-', trailing '='
    padding stripped — prefixed with 'u!'. Works for OneDrive personal,
    OneDrive for Business and SharePoint share links alike.
    """
    import base64

    encoded = base64.urlsafe_b64encode(url.encode("utf-8")).decode("ascii")
    return "u!" + encoded.rstrip("=")


def _http_error_text(response) -> str:
    """Extract a human-readable error from a failed HTTP response.

    Prefers the JSON error body (Graph: ``{"error": {"code", "message"}}``,
    OAuth-style: ``{"error_description": ...}``), falling back to a plain
    status summary.
    """
    status = getattr(response, "status_code", None)
    try:
        data = response.json()
    except Exception:
        data = None
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            # Graph error body: {"error": {"code": ..., "message": ...}}.
            parts = [str(p) for p in (err.get("code"), err.get("message")) if p]
            if parts:
                return f"HTTP {status} {' — '.join(parts)}".strip()
        if data.get("error_description"):
            return f"HTTP {status} {data['error_description']}".strip()
    if status:
        return f"HTTP {status}"
    return str(response)


async def _resolve_microsoft_short_link(url: str) -> str | None:
    """Resolve a OneDrive short link (1drv.ms / onedrive.live.com) to a URL
    that carries driveId/docId.

    Walks the redirect chain (up to 6 hops) without following into the final
    HTML viewer page, returning the first hop that embeds ``resid`` or
    ``driveId``/``docId`` query params.
    """
    import httpx as _httpx

    current = url
    try:
        async with _httpx.AsyncClient(follow_redirects=False, timeout=20) as client:
            for _ in range(6):
                resp = await client.get(current)
                if _microsoft_ids(str(resp.url)):
                    return str(resp.url)
                location = resp.headers.get("location")
                if not location:
                    return None
                current = str(_httpx.URL(resp.url).join(location))
        return None
    except Exception as exc:
        logger.debug("RemoteSpreadsheetProvider: Microsoft short-link resolution failed: %s", exc)
        return None


# Zoho Sheet DATA API v2 regional hosts. The token response carries an
# api_domain, but we do not persist it, so try the common regions in order.
_ZOHO_SHEET_HOSTS = (
    "https://sheet.zoho.com",
    "https://sheet.zoho.in",
    "https://sheet.zoho.eu",
)


def _zoho_sheet_token(session, company_id: int | None):
    """Return a fresh connected Zoho access token, or None when not connected."""
    if not (session and company_id):
        return None
    try:
        from routes.zoho_oauth import get_or_refresh_zoho_token
        return get_or_refresh_zoho_token(session, company_id)
    except Exception as exc:
        logger.debug("RemoteSpreadsheetProvider: Zoho token unavailable: %s", exc)
        return None


async def _zoho_sheet_api(
    method: str,
    path: str,
    session,
    company_id: int | None,
    payload: dict | None = None,
):
    """One authenticated Zoho Sheet DATA API request across regional hosts.

    Auto-refreshes the token once on a 401 (covers a token that went stale
    between the expiry check and the request). Returns the httpx.Response on
    success (HTTP 200), otherwise None — callers fall back to the public
    export endpoints when None.
    """
    import httpx as _httpx

    token = _zoho_sheet_token(session, company_id)
    if not token:
        return None
    refreshed = False
    for host in _ZOHO_SHEET_HOSTS:
        try:
            async with _httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                headers = {"Authorization": f"Zoho-oauthtoken {token}"}
                # The API accepts form-encoded bodies for its method-style calls
                # (e.g. worksheet.list), matching Pipedream's implementation.
                resp = await client.request(
                    method, f"{host}{path}", headers=headers, data=payload
                )
                if resp.status_code == 401 and not refreshed:
                    refreshed = True
                    from routes.zoho_oauth import get_or_refresh_zoho_token
                    fresh = get_or_refresh_zoho_token(session, company_id, force=True) if session and company_id else None
                    if fresh:
                        token = fresh
                        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
                        resp = await client.request(
                            method, f"{host}{path}", headers=headers, data=payload
                        )
                if resp.status_code == 200:
                    return resp
        except Exception as exc:
            logger.debug("RemoteSpreadsheetProvider: Zoho Sheet API %s %s failed on %s: %s", method, path, host, exc)
    return None


async def _zoho_worksheets(book_id: str, session, company_id: int | None) -> list[dict[str, str]]:
    """Return real worksheet tabs [{name, gid}] for a workbook via the connected
    Zoho Sheet API. Returns [] when not connected or the API rejects the resource
    (callers then fall back to public discovery)."""
    for path, payload in (
        (f"/api/v2/{book_id}/worksheets", None),
        (f"/api/v2/{book_id}", {"method": "worksheet.list"}),
    ):
        resp = await _zoho_sheet_api("POST" if payload else "GET", path, session, company_id, payload)
        if resp is None:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        worksheets = data.get("worksheet_names") or data.get("worksheets") or []
        tabs = [
            {
                "name": str(w.get("worksheet_name") or w.get("name") or ""),
                "gid": str(w.get("worksheet_id") or w.get("id") or ""),
            }
            for w in worksheets
            if isinstance(w, dict) and (w.get("worksheet_name") or w.get("name"))
        ]
        if tabs:
            return tabs
    return []


async def _zoho_workbook_name(book_id: str, session, company_id: int | None) -> str | None:
    """Best-effort workbook name via the connected Zoho Sheet DATA API.

    The human-readable name is NOT part of the worksheet.list response (which
    only carries worksheet_names) — it is returned by workbook.list
    (POST /workbooks), keyed by resource_id. Returns None when not connected
    or the API rejects the resource — the UI then leaves the name empty.
    """
    resp = await _zoho_sheet_api("POST", "/api/v2/workbooks", session, company_id, {"method": "workbook.list"})
    if resp is None:
        return None
    try:
        data = resp.json()
    except Exception:
        return None
    workbooks = data.get("workbooks") if isinstance(data, dict) else None
    if not isinstance(workbooks, list):
        return None
    for wb in workbooks:
        if not isinstance(wb, dict):
            continue
        if str(wb.get("resource_id") or "") != str(book_id):
            continue
        name = wb.get("workbook_name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return None


# WorkDrive binary content downloads go through download.zoho.com (per Zoho's
# docs: "File Content Download APIs should be used through download.zoho.com").
_ZOHO_WORKDRIVE_DOWNLOAD_HOSTS = (
    "https://download.zoho.com",
    "https://download.zoho.in",
    "https://download.zoho.eu",
)


def _looks_parseable(content: bytes, content_type: str) -> bool:
    """True when a downloaded workbook can be parsed by _parse_product_file
    (xlsx/xls/csv). Rejects HTML error pages and native Zoho Sheet binaries we
    cannot parse, so the caller falls through to the next download candidate."""
    ct = content_type.lower()
    if "text/html" in ct:
        return False
    if content[:4] == b"PK\x03\x04":  # xlsx / zip container
        return True
    if content[:4] == b"\xd0\xcf\x11\xe0":  # OLE2 — legacy .xls
        return True
    if any(k in ct for k in ("csv", "excel", "spreadsheet")):
        return True
    try:
        head = content[:500].decode("utf-8")
    except Exception:
        return False
    # HTML login/error pages can arrive with a generic content-type.
    if "<html" in head.lower() or "<!doctype" in head.lower():
        return False
    return "\n" in head or "," in head  # loose CSV sniff


def _not_a_spreadsheet_message(url: str, content_type: str) -> str:
    """Human-readable reason a downloaded payload isn't a usable workbook."""
    host = urlparse(url).netloc.lower()
    if "books.zoho.com" in host:
        return (
            "This looks like a Zoho Books web page, not a spreadsheet link. "
            "Use the Zoho Books source type and enter your Organization ID instead."
        )
    if "text/html" in content_type.lower():
        return (
            "This link returned an HTML page instead of a spreadsheet "
            f"(content-type: {content_type}). Make sure it's a direct Excel/CSV download link."
        )
    return (
        "This link did not return spreadsheet content "
        f"(content-type: {content_type or 'unknown'}). "
        "Make sure it's a direct Excel (.xlsx/.xls) or CSV file link."
    )


async def _zoho_workdrive_download(book_id: str, session, company_id: int | None):
    """Download a WorkDrive-hosted workbook's binary content across regions.

    Requires BOTH WorkDrive.files.READ and ZohoFiles.files.READ scopes (a
    missing ZohoFiles.files.READ returns 401 INVALID_OAUTHSCOPE). Auto-refreshes
    the token once on 401. Returns (content, content_type) on success, else
    None — callers fall back to the public export.
    """
    import httpx as _httpx

    token = _zoho_sheet_token(session, company_id)
    if not token:
        return None
    refreshed = False
    for host in _ZOHO_WORKDRIVE_DOWNLOAD_HOSTS:
        try:
            async with _httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                headers = {"Authorization": f"Zoho-oauthtoken {token}"}
                resp = await client.get(f"{host}/v1/workdrive/download/{book_id}", headers=headers)
                if resp.status_code == 401 and not refreshed:
                    refreshed = True
                    from routes.zoho_oauth import get_or_refresh_zoho_token
                    fresh = get_or_refresh_zoho_token(session, company_id, force=True) if session and company_id else None
                    if fresh:
                        token = fresh
                        headers = {"Authorization": f"Zoho-oauthtoken {token}"}
                        resp = await client.get(f"{host}/v1/workdrive/download/{book_id}", headers=headers)
                if resp.status_code == 200 and resp.content and _looks_parseable(resp.content, resp.headers.get("content-type", "")):
                    return resp.content, resp.headers.get("content-type", "")
        except Exception as exc:
            logger.debug("RemoteSpreadsheetProvider: WorkDrive download failed on %s: %s", host, exc)
    return None


class RemoteSpreadsheetProvider(InventoryProvider):
    def __init__(self, config: dict, priority: int = 80, session=None, company_id: int | None = None):
        self.priority = priority
        self.config = config
        self.session = session
        self.company_id = company_id
        self.url = str(config.get("url") or "").strip()
        self.resolved_share_url: str | None = None
        self._cache: list[dict] | None = None

    async def _download(self) -> tuple[bytes, str]:
        headers: dict[str, str] = {}
        url = self.url
        host = urlparse(url).netloc.lower()
        if "excel.cloud.microsoft" in host or "onedrive" in host or "sharepoint" in host or "1drv.ms" in host:
            # Auto-refresh path: get_or_refresh_microsoft_token exchanges the
            # stored refresh token when the access token is expired/close to
            # expiry, so long-running inventory reads never 401 after ~1 hour.
            from routes.microsoft_oauth import get_or_refresh_microsoft_token
            token = get_or_refresh_microsoft_token(self.session, self.company_id) if self.session and self.company_id else None
            if not token:
                raise ValueError("Connect Microsoft 365 before reading this Excel workbook")
            headers["Authorization"] = f"Bearer {token}"

            # Short share links (1drv.ms / onedrive.live.com) carry no
            # driveId/docId — follow the redirect chain to a canonical URL.
            share_url = url
            ids = _microsoft_ids(url)
            if not ids:
                resolved = await _resolve_microsoft_short_link(url)
                if resolved:
                    logger.info("RemoteSpreadsheetProvider: resolved Microsoft short link -> %s", resolved)
                    share_url = resolved
                    ids = _microsoft_ids(resolved)
            self.resolved_share_url = share_url

            # Candidate download URLs in preference order:
            # 1. Direct drive content URL — works for SharePoint / OneDrive for
            #    Business links that expose driveId/docId.
            # 2. Graph sharing API — the only reliable route for consumer
            #    OneDrive links, where Graph rejects the resid= drive/item pair
            #    with 400 and the direct URL cannot work. Graph resolves the
            #    sharing link server-side, so the canonical (resolved) URL is
            #    preferred, with the original short link as a last resort.
            candidates: list[str] = []
            if ids:
                drive_id, item_id = ids
                candidates.append(f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content")
            candidates.append(f"https://graph.microsoft.com/v1.0/shares/{_encode_sharing_url(share_url)}/driveItem/content")
            if share_url != url:
                candidates.append(f"https://graph.microsoft.com/v1.0/shares/{_encode_sharing_url(url)}/driveItem/content")

            last_error = ""
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                for candidate in candidates:
                    request_headers = dict(headers)
                    if "/shares/" in candidate:
                        # Redeem one-shot access to the shared item so external
                        # and consumer OneDrive links resolve for this request.
                        request_headers["Prefer"] = "redeemSharingLinkIfNecessary"
                    response = await client.get(candidate, headers=request_headers)
                    if response.status_code == 401:
                        # The token went stale between the expiry check and the
                        # request (or its exp claim was unreadable). Force one
                        # refresh and retry before surfacing a connection error.
                        refreshed = get_or_refresh_microsoft_token(self.session, self.company_id, force=True) if self.session and self.company_id else None
                        if refreshed:
                            headers["Authorization"] = f"Bearer {refreshed}"
                            request_headers["Authorization"] = f"Bearer {refreshed}"
                            response = await client.get(candidate, headers=request_headers)
                        else:
                            raise ValueError(
                                "Microsoft 365 connection expired — reconnect in Settings to read this Excel workbook."
                            )
                    if response.status_code == 200 and response.content:
                        return response.content, response.headers.get("content-type", "")
                    candidate_error = f"{_http_error_text(response)} [{candidate}]"
                    # Prefer the most informative failure (one carrying an
                    # upstream error.message over a bare HTTP status).
                    if not last_error or len(candidate_error) > len(f"HTTP {response.status_code} [{candidate}]"):
                        last_error = candidate_error
            raise ValueError(
                f"Could not download this Excel workbook from Microsoft 365 "
                f"(last response: {last_error}). Make sure the file is shared "
                "with the connected Microsoft 365 account."
            )
        elif "zohopublic.com" in host or "sheet.zoho.com" in host:
            book_id = _zoho_book_id(url)
            if not book_id:
                raise ValueError("Could not extract the Zoho Sheet workbook ID")
            # Connected path first: download the actual workbook through the
            # Zoho Sheet DATA API (live data, ALL tabs). Falls back to the
            # public CSV export below when not connected or the API rejects
            # the resource (e.g. a workbook not owned by the connected account).
            api_resp = await _zoho_sheet_api("GET", f"/api/v2/{book_id}/download", self.session, self.company_id)
            if api_resp is not None and api_resp.content and "text/html" not in api_resp.headers.get("content-type", "").lower():
                logger.info(
                    "RemoteSpreadsheetProvider: downloaded Zoho workbook via connected Sheet API book_id=%s bytes=%d",
                    book_id,
                    len(api_resp.content),
                )
                return api_resp.content, api_resp.headers.get("content-type", "")
            logger.info(
                "RemoteSpreadsheetProvider: connected Sheet API download unavailable for book_id=%s — trying WorkDrive API",
                book_id,
            )
            # WorkDrive-hosted workbooks are served by download.zoho.com (needs
            # WorkDrive.files.READ + ZohoFiles.files.READ scopes). Only accept
            # the result when it looks like a parseable xlsx/csv.
            wd_result = await _zoho_workdrive_download(book_id, self.session, self.company_id)
            if wd_result is not None:
                logger.info(
                    "RemoteSpreadsheetProvider: downloaded Zoho workbook via WorkDrive API book_id=%s bytes=%d",
                    book_id,
                    len(wd_result[0]),
                )
                return wd_result
            logger.info(
                "RemoteSpreadsheetProvider: WorkDrive download unavailable for book_id=%s — using public export",
                book_id,
            )
            zoho_token = None
            if self.session and self.company_id:
                try:
                    from routes.zoho_oauth import get_company_zoho_token
                    zoho_token = get_company_zoho_token(self.session, self.company_id)
                except Exception as exc:
                    logger.debug("RemoteSpreadsheetProvider: Zoho token unavailable: %s", exc)
            if zoho_token:
                headers["Authorization"] = f"Zoho-oauthtoken {zoho_token}"
            candidates = _zoho_export_urls(book_id, self.config.get("sheet_name"))
            last_error = ""
            async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                for candidate in candidates:
                    response = await client.get(candidate, headers=headers)
                    content_type = response.headers.get("content-type", "").lower()
                    if response.status_code == 200 and response.content and "text/html" not in content_type:
                        return response.content, content_type
                    last_error = f"{_http_error_text(response)} [{candidate}] content-type={content_type}"
            raise ValueError(
                "Zoho workbook is not downloadable publicly; enable public download/export "
                f"for the sheet (last response: {last_error})"
            )
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 401 and "graph.microsoft.com" in url:
                # The token went stale between the expiry check and the request
                # (or its exp claim was unreadable). Force one refresh and retry
                # before surfacing a connection error.
                from routes.microsoft_oauth import get_or_refresh_microsoft_token
                refreshed = get_or_refresh_microsoft_token(self.session, self.company_id, force=True) if self.session and self.company_id else None
                if refreshed:
                    headers["Authorization"] = f"Bearer {refreshed}"
                    response = await client.get(url, headers=headers)
                else:
                    raise ValueError(
                        "Microsoft 365 connection expired — reconnect in Settings to read this Excel workbook."
                    )
            if response.status_code >= 400:
                raise ValueError(f"Could not read this workbook ({_http_error_text(response)}).")
            content_type = response.headers.get("content-type", "")
            if not _looks_parseable(response.content, content_type):
                raise ValueError(_not_a_spreadsheet_message(url, content_type))
            return response.content, content_type

    async def _rows(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        content, content_type = await self._download()
        from routes.products import _parse_product_file
        filename = "inventory.xlsx" if (
            "spreadsheet" in content_type or "excel" in content_type or content[:4] == b"PK\x03\x04"
        ) else "inventory.csv"
        try:
            self._cache = _parse_product_file(content, filename, sheet_name=self.config.get("sheet_name"))
        except KeyError:
            # The stored tab name no longer exists (e.g. discovery ran on the
            # public CSV while the connected API returned a different workbook,
            # or the tab was renamed). Fall back to the first sheet.
            logger.warning(
                "RemoteSpreadsheetProvider: sheet %r not found in workbook url=%s — using first sheet",
                self.config.get("sheet_name"),
                self.url,
            )
            self._cache = _parse_product_file(content, filename, sheet_name=None)
        logger.info("RemoteSpreadsheetProvider: loaded %d rows url=%s", len(self._cache), self.url)
        return self._cache

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        wanted = sku.strip().lower()
        for row in await self._rows():
            if str(row.get("sku") or "").strip().lower() == wanted:
                return {**row, "source": "remote_spreadsheet"}
        return None

    async def search(self, query: str) -> list[dict]:
        q = query.lower().strip()
        fields = ("name", "sku", "brand", "category", "description", "model_number")
        return [{**row, "source": "remote_spreadsheet"} for row in await self._rows()
                if any(q in str(row.get(field) or "").lower() for field in fields)][:20]

    async def reserve(self, sku: str, qty: int) -> bool:
        return False


async def _microsoft_workbook_name(share_url: str, session, company_id: int | None) -> str | None:
    """Best-effort Graph lookup of the shared workbook's display name.

    Uses /shares/{u!...}/driveItem, which returns the real file name
    (e.g. "inventory.xlsx") for both consumer OneDrive and business links.
    Never raises — failures just mean no name for the UI to auto-fill.
    """
    from routes.microsoft_oauth import get_or_refresh_microsoft_token
    token = get_or_refresh_microsoft_token(session, company_id) if session and company_id else None
    if not token:
        return None
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(
                f"https://graph.microsoft.com/v1.0/shares/{_encode_sharing_url(share_url)}/driveItem",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Prefer": "redeemSharingLinkIfNecessary",
                },
            )
            if resp.status_code == 200:
                name = resp.json().get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()
    except Exception:
        pass
    return None


async def list_remote_worksheets(url: str, session=None, company_id: int | None = None) -> tuple[list[dict[str, str]], str | None]:
    """Return (tabs, workbook_name) for a remote spreadsheet URL.

    ``workbook_name`` is best-effort display metadata used to auto-fill the
    source name in the UI; it is None when not derivable.
    """
    host = urlparse(url).netloc.lower()
    if "zohopublic.com" in host or "sheet.zoho.com" in host:
        book_id = _zoho_book_id(url)
        if not book_id:
            raise ValueError("Could not extract the Zoho Sheet workbook ID")
        # Connected path first: list the REAL worksheet tabs via the Sheet API
        # so the user can pick the live tab (e.g. "calls"). Falls back to
        # public discovery when not connected or the API rejects the resource.
        workbook_name = await _zoho_workbook_name(book_id, session, company_id)
        connected_tabs = await _zoho_worksheets(book_id, session, company_id)
        if connected_tabs:
            logger.info(
                "[inventory_sources] zoho sheet tabs via connected API book_id=%s tabs=%s",
                book_id,
                [t["name"] for t in connected_tabs],
            )
            return connected_tabs, workbook_name
        provider = RemoteSpreadsheetProvider({"url": url}, session=session, company_id=company_id)
        content, content_type = await provider._download()
        if "spreadsheet" in content_type or "excel" in content_type or content[:4] == b"PK\x03\x04":
            import pandas as pd
            return [{"name": name, "gid": str(i)} for i, name in enumerate(pd.ExcelFile(io.BytesIO(content)).sheet_names)], workbook_name
        return [{"name": "Sheet 1", "gid": "0"}], workbook_name
    provider = RemoteSpreadsheetProvider({"url": url}, session=session, company_id=company_id)
    content, content_type = await provider._download()
    if "spreadsheet" in content_type or "excel" in content_type or content[:4] == b"PK\x03\x04" or url.lower().split("?")[0].endswith((".xlsx", ".xls")):
        import pandas as pd
        tabs = [{"name": name, "gid": str(i)} for i, name in enumerate(pd.ExcelFile(io.BytesIO(content)).sheet_names)]
    else:
        tabs = [{"name": "Sheet 1", "gid": "0"}]
    name = None
    if any(k in host for k in ("excel.cloud.microsoft", "onedrive", "sharepoint", "1drv.ms")):
        name = await _microsoft_workbook_name(provider.resolved_share_url or url, session, company_id)
    return tabs, name
