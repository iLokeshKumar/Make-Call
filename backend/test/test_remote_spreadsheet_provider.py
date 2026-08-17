from __future__ import annotations

import base64
import io
import json
import sys
import types

import pytest

from openpyxl import Workbook

from services.inventory import remote_spreadsheet_provider as provider_mod


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {"content-type": "application/octet-stream"}

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class _FakeAsyncClient:
    urls: list[str] = []
    responses: dict[str, tuple[int, bytes, dict]] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url: str, headers: dict | None = None) -> _FakeResponse:
        del headers
        self.urls.append(url)
        status, content, resp_headers = self.responses.get(url, (404, b"", {}))
        return _FakeResponse(content, status, resp_headers)

    async def request(self, method: str, url: str, headers: dict | None = None, data=None) -> _FakeResponse:
        del method, headers, data
        self.urls.append(url)
        status, content, resp_headers = self.responses.get(url, (404, b"", {}))
        return _FakeResponse(content, status, resp_headers)


XLSX_BYTES = b"PK\x03\x04fake-xlsx-content"
XLSX_CONTENT_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# URL shape from the reported failure: a 1drv.ms short link whose redirect
# chain lands on a consumer OneDrive URL carrying resid=DRIVEID!ITEMID.
SHORT_LINK = "https://1drv.ms/x/c/5fe8acda98835301/IQAZ-R-E_ZoCT7g7aGGZkSRWAe351RcwqBcJtsE-y4u5T5k?e=y2IPc3"
RESOLVED_LINK = (
    "https://onedrive.live.com/:x:/g/personal/5FE8ACDA98835301/"
    "IQAZ-R-E_ZoCT7g7aGGZkSRWAe351RcwqBcJtsE-y4u5T5k"
    "?resid=5FE8ACDA98835301!s841ff9199afd4f02b83b686199912456"
    "&ithint=file%2cxlsx&e=y2IPc3&migratedtospo=true"
    "&redeem=aHR0cHM6Ly8xZHJ2Lm1zL3gvYy81ZmU4YWNkYTk4ODM1MzAxL0lRQVotUi1FX1pvQ1Q3ZzdhR0daa1NSV0FlMzUxUmN3cUJjSnRzRS15NHU1VDVrP2U9eTJJUGMz"
)
DIRECT_URL = "https://graph.microsoft.com/v1.0/drives/5FE8ACDA98835301/items/s841ff9199afd4f02b83b686199912456/content"
SHARES_RESOLVED_URL = f"https://graph.microsoft.com/v1.0/shares/{provider_mod._encode_sharing_url(RESOLVED_LINK)}/driveItem/content"
SHARES_SHORT_URL = f"https://graph.microsoft.com/v1.0/shares/{provider_mod._encode_sharing_url(SHORT_LINK)}/driveItem/content"


def _install_zoho_token_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the routes.zoho_oauth module imported inside the Zoho Sheet API."""
    routes_mod = types.ModuleType("routes")
    zoho_mod = types.ModuleType("routes.zoho_oauth")
    zoho_mod.get_or_refresh_zoho_token = lambda session, company_id, force=False: "zoho-token"
    monkeypatch.setitem(sys.modules, "routes", routes_mod)
    monkeypatch.setitem(sys.modules, "routes.zoho_oauth", zoho_mod)


def _install_microsoft_token_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the routes.microsoft_oauth module imported inside _download."""
    routes_mod = types.ModuleType("routes")
    microsoft_mod = types.ModuleType("routes.microsoft_oauth")
    microsoft_mod.get_or_refresh_microsoft_token = lambda session, company_id, force=False: "fake-token"
    monkeypatch.setitem(sys.modules, "routes", routes_mod)
    monkeypatch.setitem(sys.modules, "routes.microsoft_oauth", microsoft_mod)


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.urls = []
    _FakeAsyncClient.responses = {}
    yield
    _FakeAsyncClient.urls = []
    _FakeAsyncClient.responses = {}


def test_encode_sharing_url_matches_graph_format() -> None:
    url = "https://onedrive.live.com/redir?resid=1231244193912!12&authKey=1201919!12921!1"

    encoded = provider_mod._encode_sharing_url(url)

    assert encoded.startswith("u!")
    body = encoded[2:]
    # Unpadded base64url: no '=', '/' or '+'.
    assert "=" not in body
    assert "/" not in body
    assert "+" not in body
    assert base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)).decode() == url


async def test_consumer_onedrive_link_falls_back_to_shares_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """A consumer OneDrive link (resid= IDs, direct download -> 400) must
    succeed via Graph's /shares sharing API — the reported bug."""
    async def _resolve(url: str) -> str | None:
        del url
        return RESOLVED_LINK

    monkeypatch.setattr(provider_mod, "_resolve_microsoft_short_link", _resolve)
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_microsoft_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        # The direct drive/item content URL is rejected for consumer OneDrive.
        DIRECT_URL: (400, b"", {}),
        SHARES_RESOLVED_URL: (200, XLSX_BYTES, {"content-type": XLSX_CONTENT_TYPE}),
        SHARES_SHORT_URL: (200, XLSX_BYTES, {"content-type": XLSX_CONTENT_TYPE}),
    }

    # Production (services/inventory/factory.py) always passes a session and
    # company_id; _download refuses to look up a token without them.
    provider = provider_mod.RemoteSpreadsheetProvider({"url": SHORT_LINK}, session=object(), company_id=1)
    content, content_type = await provider._download()

    assert content == XLSX_BYTES
    assert content_type == XLSX_CONTENT_TYPE
    # The failing direct URL is attempted first, then the sharing-API fallback
    # (canonical resolved link) succeeds — the original short link is never
    # reached.
    assert _FakeAsyncClient.urls == [DIRECT_URL, SHARES_RESOLVED_URL]
    assert SHARES_SHORT_URL not in _FakeAsyncClient.urls


async def test_sharepoint_link_with_drive_id_uses_direct_content_url(monkeypatch: pytest.MonkeyPatch) -> None:
    """SharePoint links that expose driveId/docId keep using the direct drive
    content URL and never touch /shares when it succeeds."""
    url = (
        "https://contoso-my.sharepoint.com/personal/a_b_contoso_com/_layouts/15/onedrive.aspx"
        "?id=%2Fdocuments%2Finventory.xlsx&driveId=b%21abc123&docId=01XYZ789"
    )
    direct = "https://graph.microsoft.com/v1.0/drives/b!abc123/items/01XYZ789/content"

    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_microsoft_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        direct: (200, XLSX_BYTES, {"content-type": XLSX_CONTENT_TYPE}),
    }

    provider = provider_mod.RemoteSpreadsheetProvider({"url": url}, session=object(), company_id=1)
    content, content_type = await provider._download()

    assert content == XLSX_BYTES
    assert content_type == XLSX_CONTENT_TYPE
    assert _FakeAsyncClient.urls == [direct]


async def test_all_download_candidates_fail_surface_graph_error_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """When every candidate fails, the raised ValueError carries the real
    Graph error body (error.message) so the route can surface it to the user
    instead of a generic message."""
    async def _resolve(url: str) -> str | None:
        del url
        return RESOLVED_LINK

    monkeypatch.setattr(provider_mod, "_resolve_microsoft_short_link", _resolve)
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_microsoft_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        DIRECT_URL: (400, json.dumps({"error": {"code": "invalidRequest", "message": "The request is malformed or incorrect."}}).encode(), {"content-type": "application/json"}),
        SHARES_RESOLVED_URL: (403, json.dumps({"error": {"code": "accessDenied", "message": "Access denied. The user does not have permission to access this item."}}).encode(), {"content-type": "application/json"}),
        SHARES_SHORT_URL: (404, b"", {}),
    }

    provider = provider_mod.RemoteSpreadsheetProvider({"url": SHORT_LINK}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider._download()

    message = str(excinfo.value)
    assert "HTTP 403" in message
    assert "accessDenied" in message
    assert "Access denied. The user does not have permission to access this item." in message


def test_http_error_text_extracts_graph_error_body() -> None:
    graph = _FakeResponse(
        json.dumps({"error": {"code": "invalidRequest", "message": "The request is malformed or incorrect."}}).encode(),
        status_code=400,
        headers={"content-type": "application/json"},
    )
    assert provider_mod._http_error_text(graph) == (
        "HTTP 400 invalidRequest — The request is malformed or incorrect."
    )

    oauth = _FakeResponse(
        b'{"error_description": "The refresh token is invalid."}',
        status_code=401,
        headers={"content-type": "application/json"},
    )
    assert provider_mod._http_error_text(oauth) == "HTTP 401 The refresh token is invalid."

    bare = _FakeResponse(b"", status_code=404)
    assert provider_mod._http_error_text(bare) == "HTTP 404"


def _make_xlsx() -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"
    ws.append(["name", "sku", "stock"])
    ws.append(["OLED Monitor", "MON-1", 5])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def test_microsoft_workbook_name_uses_shares_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_microsoft_token_stub(monkeypatch)
    meta_url = f"https://graph.microsoft.com/v1.0/shares/{provider_mod._encode_sharing_url(RESOLVED_LINK)}/driveItem"
    _FakeAsyncClient.responses = {
        meta_url: (200, json.dumps({"name": "stock.xlsx"}).encode(), {"content-type": "application/json"}),
    }

    name = await provider_mod._microsoft_workbook_name(RESOLVED_LINK, session=object(), company_id=1)

    assert name == "stock.xlsx"
    assert _FakeAsyncClient.urls == [meta_url]


async def test_microsoft_workbook_name_none_when_metadata_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_microsoft_token_stub(monkeypatch)
    meta_url = f"https://graph.microsoft.com/v1.0/shares/{provider_mod._encode_sharing_url(RESOLVED_LINK)}/driveItem"
    _FakeAsyncClient.responses = {meta_url: (404, b"", {})}

    assert await provider_mod._microsoft_workbook_name(RESOLVED_LINK, session=object(), company_id=1) is None


async def test_list_remote_worksheets_returns_tabs_and_workbook_name(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve(url: str) -> str | None:
        del url
        return RESOLVED_LINK

    monkeypatch.setattr(provider_mod, "_resolve_microsoft_short_link", _resolve)
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_microsoft_token_stub(monkeypatch)
    meta_url = f"https://graph.microsoft.com/v1.0/shares/{provider_mod._encode_sharing_url(RESOLVED_LINK)}/driveItem"
    xlsx = _make_xlsx()
    _FakeAsyncClient.responses = {
        DIRECT_URL: (400, b"", {}),
        SHARES_RESOLVED_URL: (200, xlsx, {"content-type": XLSX_CONTENT_TYPE}),
        SHARES_SHORT_URL: (200, xlsx, {"content-type": XLSX_CONTENT_TYPE}),
        meta_url: (200, json.dumps({"name": "stock.xlsx"}).encode(), {"content-type": "application/json"}),
    }

    tabs, name = await provider_mod.list_remote_worksheets(SHORT_LINK, session=object(), company_id=1)

    assert name == "stock.xlsx"
    assert tabs == [{"name": "Inventory", "gid": "0"}]


ZOHO_URL = "https://sheet.zoho.com/sheet/open/abc123book"
ZOHO_API_URL = "https://sheet.zoho.com/api/v2/abc123book"
ZOHO_WORKBOOKS_URL = "https://sheet.zoho.com/api/v2/workbooks"


def _zoho_workbook_list_json(book_id: str, name: str) -> bytes:
    return json.dumps({
        "workbooks": [{"resource_id": book_id, "workbook_name": name}],
    }).encode()


async def test_zoho_workbook_name_from_workbook_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_zoho_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        ZOHO_WORKBOOKS_URL: (200, _zoho_workbook_list_json("abc123book", "StockBook"), {"content-type": "application/json"}),
    }

    name = await provider_mod._zoho_workbook_name("abc123book", session=object(), company_id=1)

    assert name == "StockBook"
    assert _FakeAsyncClient.urls == [ZOHO_WORKBOOKS_URL]


async def test_zoho_workbook_name_matches_resource_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """The name is looked up by matching resource_id, not by position — other
    workbooks in the list must not leak through."""
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_zoho_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        ZOHO_WORKBOOKS_URL: (
            200,
            json.dumps({
                "workbooks": [
                    {"resource_id": "otherbook", "workbook_name": "OtherBook"},
                    {"resource_id": "abc123book", "workbook_name": "StockBook"},
                ],
            }).encode(),
            {"content-type": "application/json"},
        ),
    }

    name = await provider_mod._zoho_workbook_name("abc123book", session=object(), company_id=1)

    assert name == "StockBook"


async def test_zoho_workbook_name_none_when_not_connected() -> None:
    # No session/company_id → no token → None (same shape as not connected).
    assert await provider_mod._zoho_workbook_name("abc123book", session=None, company_id=None) is None


async def test_zoho_workbook_name_none_when_book_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_zoho_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        ZOHO_WORKBOOKS_URL: (200, _zoho_workbook_list_json("otherbook", "OtherBook"), {"content-type": "application/json"}),
    }

    assert await provider_mod._zoho_workbook_name("abc123book", session=object(), company_id=1) is None


async def test_list_remote_worksheets_zoho_returns_tabs_and_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _install_zoho_token_stub(monkeypatch)
    _FakeAsyncClient.responses = {
        ZOHO_WORKBOOKS_URL: (200, _zoho_workbook_list_json("abc123book", "StockBook"), {"content-type": "application/json"}),
        ZOHO_API_URL: (
            200,
            json.dumps({
                "worksheet_names": [
                    {"worksheet_name": "Inventory", "worksheet_id": "0"},
                    {"worksheet_name": "Sheet2", "worksheet_id": "1"},
                ],
            }).encode(),
            {"content-type": "application/json"},
        ),
    }

    tabs, name = await provider_mod.list_remote_worksheets(ZOHO_URL, session=object(), company_id=1)

    assert name == "StockBook"
    assert tabs == [
        {"name": "Inventory", "gid": "0"},
        {"name": "Sheet2", "gid": "1"},
    ]


# --- Generic download tail: reject non-spreadsheet payloads (the reported
# books.zoho.com login-page false positive) ---

BOOKS_WEB_URL = "https://books.zoho.com/app/935322145#/quotes?filter_by=Status.All&per_page=25"
LOGIN_HTML = b"<html><body>Sign in to Zoho Books</body></html>"


async def test_generic_download_rejects_html_login_page(monkeypatch: pytest.MonkeyPatch) -> None:
    """A web URL that resolves to an HTML login page must raise instead of
    being silently accepted as a workbook (the reported false positive)."""
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {
        BOOKS_WEB_URL: (200, LOGIN_HTML, {"content-type": "text/html"}),
    }

    provider = provider_mod.RemoteSpreadsheetProvider({"url": BOOKS_WEB_URL}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider._download()

    message = str(excinfo.value)
    assert "Zoho Books web page" in message
    assert "Organization ID" in message


async def test_generic_download_rejects_html_with_generic_content_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTML error pages served with a non-HTML content-type are sniffed out too."""
    url = "https://example.com/inventory.xlsx"
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {
        url: (200, LOGIN_HTML, {"content-type": "application/octet-stream"}),
    }

    provider = provider_mod.RemoteSpreadsheetProvider({"url": url}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider._download()

    # The HTML body is sniffed out and rejected (content-type alone doesn't
    # save it) — the message comes from the generic branch.
    assert "did not return spreadsheet content" in str(excinfo.value)


async def test_generic_download_accepts_real_xlsx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Real spreadsheet payloads still flow through the generic tail."""
    url = "https://cdn.example.com/inventory.xlsx"
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {
        url: (200, _make_xlsx(), {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),
    }

    provider = provider_mod.RemoteSpreadsheetProvider({"url": url}, session=object(), company_id=1)
    content, content_type = await provider._download()

    assert content == _make_xlsx()
    assert "spreadsheetml" in content_type


async def test_generic_download_accepts_plain_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plain-text CSV (e.g. from a public export endpoint) is still accepted."""
    url = "https://example.com/export?format=csv"
    csv_bytes = b"name,sku,stock\nOLED Monitor,MON-1,5\n"
    monkeypatch.setattr(provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {
        url: (200, csv_bytes, {"content-type": "text/csv"}),
    }

    provider = provider_mod.RemoteSpreadsheetProvider({"url": url}, session=object(), company_id=1)
    content, content_type = await provider._download()

    assert content == csv_bytes
    assert content_type == "text/csv"
