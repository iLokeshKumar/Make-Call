"""
google_sheets_provider.py - Inventory provider that reads from a public Google Sheet.

The sheet must be shared as "Anyone with the link can view".
No API key is required — we fetch the public CSV export endpoint.

Config fields expected in InventorySource.config_json:
  url        — full Google Sheets URL  (e.g. https://docs.google.com/spreadsheets/d/ID/edit#gid=0)
  gid        — optional tab/sheet gid
  sheet_name — optional worksheet/tab name

If no tab is configured, the provider tries likely inventory tab names first
and only then falls back to the spreadsheet's default/first visible tab.
"""
from __future__ import annotations

import logging
import re
import time
import html
import json
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, quote, urlparse

import httpx

from services.inventory.base import InventoryProvider

logger = logging.getLogger(__name__)

# Module-level cache: cache_key → (fetched_at, rows)
_CACHE: dict[str, tuple[float, list[dict]]] = {}
_CACHE_TTL = 300  # 5 minutes

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _extract_sheet_id(url: str) -> str | None:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url)
    return m.group(1) if m else None


def _extract_gid(url: str) -> str | None:
    parsed = urlparse(url)
    for part in (parsed.query, parsed.fragment):
        gid = parse_qs(part).get("gid", [None])[0]
        if gid:
            return gid
    return None


def _export_url(sheet_id: str, gid: str | None = None, sheet_name: str | None = None) -> str:
    if sheet_name:
        return f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:csv&sheet={quote(sheet_name)}"
    base = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
    return f"{base}&gid={gid}" if gid else base


def _decode_js_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except Exception:
        return value.replace(r"\/", "/").replace(r"\"", '"').replace(r"\\", "\\")


def _parse_public_sheet_tabs(page_html: str) -> list[dict[str, str]]:
    tabs: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(gid: str | None, name: str | None) -> None:
        if not gid or not name or gid in seen:
            return
        decoded = html.unescape(_decode_js_string(name)).strip()
        if not decoded or len(decoded) > 120:
            return
        seen.add(gid)
        tabs.append({"name": decoded, "gid": gid})

    bodies = [page_html, html.unescape(page_html)]
    patterns = [
        # JSON key-value pairs: "gid":"N"..."name":"SheetName" (and reverse)
        re.compile(r'"gid"\s*:\s*"?(?P<gid>\d+)"?[^{}]{0,240}?"name"\s*:\s*"(?P<name>(?:\\.|[^"\\])+)'),
        re.compile(r'"name"\s*:\s*"(?P<name>(?:\\.|[^"\\])+)"[^{}]{0,240}?"gid"\s*:\s*"?(?P<gid>\d+)"?'),
        # Google Sheets v4 properties: "sheetId":N..."title":"Name" within same JSON object
        re.compile(r'"sheetId"\s*:\s*(?P<gid>\d+)[^{}]{0,400}?"title"\s*:\s*"(?P<name>(?:\\.|[^"\\])+)"'),
        re.compile(r'"title"\s*:\s*"(?P<name>(?:\\.|[^"\\])+)"[^{}]{0,400}?"sheetId"\s*:\s*(?P<gid>\d+)'),
        # Newer bootstrapData: "id":N..."title":"Name"
        re.compile(r'"id"\s*:\s*(?P<gid>\d{1,12})\b[^{}]{0,400}?"title"\s*:\s*"(?P<name>(?:\\.|[^"\\])+)"'),
        # Serialized tuple: [gid,"name",...,GRID]
        re.compile(r'\[(?P<gid>\d+)\s*,\s*"(?P<name>(?:\\.|[^"\\])+)".{0,160}?\bGRID\b'),
        # HTML: href="#gid=N" or href="...?gid=N" with name immediately following the tag close
        re.compile(r'href=["\']?[^"\'<>]*[#?&]gid=(?P<gid>\d+)[^"\'<>]*["\']?[^>]*>(?P<name>[^<]{1,120}?)\s*</'),
        # data-gid="N" attribute (modern tab nav)
        re.compile(r'data-gid=["\'](?P<gid>\d+)["\'][^>]*>(?P<name>[^<]{1,120}?)\s*</'),
        # Legacy: gid in URL fragment, then close-tag, then name before next tag
        re.compile(r'[#?&]gid=(?P<gid>\d+)[^<]{0,500}>(?P<name>[^<\n]+?)\s*<'),
    ]
    for body in bodies:
        for pattern in patterns:
            for match in pattern.finditer(body):
                add(match.group("gid"), match.group("name"))
    return tabs


def _parse_public_sheet_title(page_html: str) -> str | None:
    """Extract the workbook title from a public Google Sheet page.

    Prefers og:title (exact sheet name), falls back to the <title> tag
    ("<SheetName> - Google Sheets").
    """
    patterns = (
        re.compile(r'<meta[^>]+(?:property|name)="og:title"[^>]+content="([^"]+)"', re.I),
        re.compile(r"<meta[^>]+(?:property|name)='og:title'[^>]+content='([^']+)'", re.I),
        re.compile(r"<title[^>]*>\s*(.*?)(?:\s*[-–—]\s*Google\s*Sheets)?\s*</title>", re.I | re.S),
    )
    for pattern in patterns:
        match = pattern.search(page_html)
        if not match:
            continue
        title = html.unescape(match.group(1)).strip()
        if title and len(title) <= 200:
            return title
    return None


async def public_sheet_title(sheet_url: str) -> str | None:
    """Best-effort fetch of a public Google Sheet's workbook title. Never
    raises — callers treat None as "no name available" for auto-fill."""
    sheet_id = _extract_sheet_id(sheet_url)
    if not sheet_id:
        return None
    headers = {"User-Agent": _BROWSER_UA}
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(
                f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview",
                headers=headers,
            )
            resp.raise_for_status()
            return _parse_public_sheet_title(resp.text)
    except Exception:
        return None


async def _gviz_api_tabs(
    client: httpx.AsyncClient, sheet_id: str, headers: dict
) -> list[dict[str, str]]:
    """
    Check sheet accessibility via Google's GViz API endpoint.
    Returns default tab if GViz responds cleanly with status: ok.
    """
    try:
        url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/gviz/tq?tqx=out:json"
        resp = await client.get(url, headers=headers)
        if resp.status_code == 200 and 'google.visualization' in resp.text:
            return [{"name": "Default Tab (Sheet 1)", "gid": "0"}]
        return []
    except Exception as exc:
        logger.debug("GoogleSheetsProvider: GViz API check failed sheet=%s: %s", sheet_id, exc)
        return []


async def list_public_worksheets(sheet_url: str) -> list[dict[str, str]]:
    sheet_id = _extract_sheet_id(sheet_url)
    if not sheet_id:
        return []

    headers = {"User-Agent": _BROWSER_UA}

    async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
        # Strategy 1: HTML scraping of /htmlview and /edit pages.
        for url in [
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/htmlview",
            f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit?usp=sharing",
        ]:
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                tabs = _parse_public_sheet_tabs(resp.text)
                if tabs:
                    logger.info(
                        "GoogleSheetsProvider: HTML scraping found %d tab(s) via %s for sheet=%s",
                        len(tabs), url, sheet_id,
                    )
                    return tabs
            except Exception as exc:
                logger.info("GoogleSheetsProvider: tab discovery failed url=%s error=%s", url, exc)

        # Strategy 2: GViz API check — confirms sheet accessibility & returns default tab.
        tabs = await _gviz_api_tabs(client, sheet_id, headers)
        if tabs:
            logger.info("GoogleSheetsProvider: GViz API confirmed sheet accessibility for sheet=%s", sheet_id)
            return tabs

    logger.warning("GoogleSheetsProvider: no worksheet tabs found for sheet=%s", sheet_id)
    return []


def invalidate(cache_key: str) -> None:
    _CACHE.pop(cache_key, None)


@dataclass(frozen=True)
class _SheetCandidate:
    label: str
    gid: str | None = None
    sheet_name: str | None = None


_INVENTORY_SHEET_CANDIDATES = (
    "Inventory",
    "Products",
    "Product",
    "Stock",
    "Catalog",
    "Items",
)


class GoogleSheetsProvider(InventoryProvider):
    def __init__(self, config: dict, priority: int = 80, company_id: Optional[int] = None):
        self.priority = priority
        self.company_id = company_id
        sheet_url = config.get("url", "")
        self._sheet_id = _extract_sheet_id(sheet_url)
        self._gid = str(config.get("gid") or _extract_gid(sheet_url) or "").strip() or None
        self._sheet_name = str(config.get("sheet_name") or "").strip() or None
        self._cache_key = f"gsheets:{self._sheet_id}:{self._gid}:{self._sheet_name}"

    def _candidates(self) -> list[_SheetCandidate]:
        if self._gid:
            return [_SheetCandidate(label=f"gid:{self._gid}", gid=self._gid)]
        if self._sheet_name:
            return [_SheetCandidate(label=f"sheet:{self._sheet_name}", sheet_name=self._sheet_name)]

        candidates = [
            _SheetCandidate(label=f"auto-sheet:{name}", sheet_name=name)
            for name in _INVENTORY_SHEET_CANDIDATES
        ]
        candidates.append(_SheetCandidate(label="default-first-tab"))
        return candidates

    async def _rows(self) -> list[dict]:
        if not self._sheet_id:
            logger.warning("GoogleSheetsProvider: invalid or missing spreadsheet URL")
            return []

        now = time.time()
        cached = _CACHE.get(self._cache_key)
        if cached and now - cached[0] < _CACHE_TTL:
            logger.info(
                "GoogleSheetsProvider: cache hit sheet=%s gid=%s sheet_name=%s rows=%d",
                self._sheet_id,
                self._gid,
                self._sheet_name,
                len(cached[1]),
            )
            return cached[1]

        from routes.products import _parse_product_file

        headers = {}
        if self.company_id:
            try:
                from database import get_session as _get_db_session
                from routes.calendar import get_company_calendar_credentials
                with next(_get_db_session()) as _session:
                    creds = get_company_calendar_credentials(_session, self.company_id)
                    if creds and creds.token:
                        headers["Authorization"] = f"Bearer {creds.token}"
            except Exception as _exc:
                logger.debug("GoogleSheetsProvider: could not load OAuth token for company %s: %s", self.company_id, _exc)

        errors: list[str] = []
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            for candidate in self._candidates():
                url = _export_url(self._sheet_id, gid=candidate.gid, sheet_name=candidate.sheet_name)
                logger.info(
                    "GoogleSheetsProvider: fetching sheet=%s candidate=%s url=%s",
                    self._sheet_id,
                    candidate.label,
                    url,
                )
                try:
                    resp = await client.get(url, headers=headers)
                    resp.raise_for_status()
                    rows = _parse_product_file(resp.content, f"{self._sheet_id}.csv")
                except Exception as exc:
                    errors.append(f"{candidate.label}: {exc}")
                    logger.info(
                        "GoogleSheetsProvider: candidate=%s failed for sheet=%s: %s",
                        candidate.label,
                        self._sheet_id,
                        exc,
                    )
                    continue

                logger.info(
                    "GoogleSheetsProvider: candidate=%s parsed rows=%d from sheet=%s",
                    candidate.label,
                    len(rows),
                    self._sheet_id,
                )
                if rows or candidate.label == "default-first-tab":
                    _CACHE[self._cache_key] = (now, rows)
                    logger.info(
                        "GoogleSheetsProvider: selected candidate=%s rows=%d sheet=%s gid=%s sheet_name=%s",
                        candidate.label,
                        len(rows),
                        self._sheet_id,
                        candidate.gid,
                        candidate.sheet_name,
                    )
                    return rows

        logger.warning(
            "GoogleSheetsProvider: no readable worksheet found for sheet=%s errors=%s",
            self._sheet_id,
            errors,
        )
        return cached[1] if cached else []

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        for row in await self._rows():
            if (row.get("sku") or "").strip().lower() == sku.strip().lower():
                return {**row, "source": "google_sheets"}
        return None

    async def search(self, query: str) -> list[dict]:
        q = query.lower()
        results = [
            {**r, "source": "google_sheets"}
            for r in await self._rows()
            if q in (r.get("name") or "").lower()
            or q in (r.get("sku") or "").lower()
            or q in (r.get("brand") or "").lower()
            or q in (r.get("category") or "").lower()
            or q in (r.get("description") or "").lower()
            or q in (r.get("model_number") or "").lower()
        ]
        return results[:20]

    async def reserve(self, sku: str, qty: int) -> bool:
        return False  # Google Sheets is read-only
