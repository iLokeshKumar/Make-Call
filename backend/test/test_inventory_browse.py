"""Tests for the connected-account browse helpers.

These list spreadsheet workbooks from OAuth-connected accounts (Microsoft
OneDrive via Graph search, Zoho via workbook.list) so users can pick a file
instead of pasting a share URL.
"""
import sys
import types

import httpx
import pytest


# Scripted responses consumed in order by _FakeClient across AsyncClient
# constructions (httpx.AsyncClient is instantiated with timeout=… kwargs, so
# the responses live at module scope instead of on the client instance).
_SCRIPTED_RESPONSES: list["_FakeResponse"] = []


class _FakeResponse:
    def __init__(self, status_code: int, json_body=None, text: str = ""):
        self.status_code = status_code
        self._json_body = json_body
        self.text = text

    def json(self):
        if self._json_body is None:
            raise ValueError("no json body")
        return self._json_body


class _FakeClient:
    """Async-context client that returns the scripted responses in order."""

    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        return self._next()

    async def post(self, url, **kwargs):
        self.calls.append(("post", url, kwargs))
        return self._next()

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self._next()

    def _next(self):
        if not _SCRIPTED_RESPONSES:
            return _FakeResponse(500, text="unexpected call")
        return _SCRIPTED_RESPONSES.pop(0)


class _FakeMSAuth:
    def __init__(self, token="ms-token"):
        self.token = token
        self.refreshed = False

    def get_or_refresh_microsoft_token(self, session, company_id, force=False):
        if force:
            self.refreshed = True
            self.token = "ms-token-fresh"
        return self.token


class _FakeZohoAuth:
    def __init__(self, token="zoho-token"):
        self.token = token
        self.refreshed = False

    def get_or_refresh_zoho_token(self, session, company_id, force=False):
        if force:
            self.refreshed = True
            self.token = "zoho-token-fresh"
        return self.token


@pytest.fixture()
def stub_oauth(monkeypatch):
    ms = _FakeMSAuth()
    zoho = _FakeZohoAuth()
    ms_mod = types.ModuleType("routes.microsoft_oauth")
    ms_mod.get_or_refresh_microsoft_token = ms.get_or_refresh_microsoft_token
    zoho_mod = types.ModuleType("routes.zoho_oauth")
    zoho_mod.get_or_refresh_zoho_token = zoho.get_or_refresh_zoho_token
    monkeypatch.setitem(sys.modules, "routes.microsoft_oauth", ms_mod)
    monkeypatch.setitem(sys.modules, "routes.zoho_oauth", zoho_mod)
    # Patch only the AsyncClient attribute — replacing the whole httpx module
    # breaks other packages (langgraph_sdk) that import httpx.HTTPStatusError.
    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    _SCRIPTED_RESPONSES[:] = []
    return ms, zoho


def test_browse_cache_hits_and_refresh_bypasses(stub_oauth, monkeypatch):
    import routes.inventory_sources as mod
    from routes.inventory_sources import browse_connected_files

    calls = {"n": 0}

    async def fake_list(session, company_id):
        calls["n"] += 1
        return {"connected": True, "files": [{"id": "1", "name": "a.xlsx", "url": "https://1drv.ms/1"}], "error": None}

    monkeypatch.setattr(mod, "_list_microsoft_workbooks", fake_list)
    mod._browse_cache.clear()
    user = types.SimpleNamespace(company_id=7)

    r1 = asyncio_run(browse_connected_files(provider="microsoft_excel", refresh=0, current_user=user, session=object()))
    assert calls["n"] == 1
    r2 = asyncio_run(browse_connected_files(provider="microsoft_excel", refresh=0, current_user=user, session=object()))
    assert calls["n"] == 1  # served from cache — helper not called again
    assert r1 == r2
    r3 = asyncio_run(browse_connected_files(provider="microsoft_excel", refresh=1, current_user=user, session=object()))
    assert calls["n"] == 2  # refresh=1 bypasses the cache
    assert r3 == r1


def test_google_listing_cached_and_refresh_bypasses(stub_oauth, monkeypatch):
    from routes.inventory_sources import list_google_drive_spreadsheets

    calls = {"n": 0}

    def fake_creds(session, company_id):
        calls["n"] += 1
        return types.SimpleNamespace(token="gtoken")

    monkeypatch.setattr("routes.calendar.get_company_calendar_credentials", fake_creds)
    routes_mod = sys.modules["routes.inventory_sources"]
    routes_mod._browse_cache.clear()
    _SCRIPTED_RESPONSES[:] = [
        # First call: about (account email) + files listing.
        _FakeResponse(200, {"user": {"emailAddress": "lokeshk431@gmail.com"}}),
        _FakeResponse(200, {"files": [{"id": "g1", "name": "Inventory", "webViewLink": "https://docs.google.com/spreadsheets/d/g1/edit"}]}),
        # refresh=1 call: about + files again.
        _FakeResponse(200, {"user": {"emailAddress": "lokeshk431@gmail.com"}}),
        _FakeResponse(200, {"files": [{"id": "g1", "name": "Inventory", "webViewLink": "https://docs.google.com/spreadsheets/d/g1/edit"}]}),
    ]
    user = types.SimpleNamespace(company_id=9)

    r1 = asyncio_run(list_google_drive_spreadsheets(refresh=0, current_user=user, session=object()))
    assert calls["n"] == 1
    r2 = asyncio_run(list_google_drive_spreadsheets(refresh=0, current_user=user, session=object()))
    assert calls["n"] == 1  # cache hit — creds not re-fetched
    assert r1 == r2
    r3 = asyncio_run(list_google_drive_spreadsheets(refresh=1, current_user=user, session=object()))
    assert calls["n"] == 2  # refresh=1 bypasses the cache
    assert r3 == r1
    assert r1["connected"] is True
    assert r1["spreadsheets"][0]["name"] == "Inventory"
    assert r1["account_email"] == "lokeshk431@gmail.com"


def test_microsoft_not_connected_returns_connected_false(stub_oauth):
    from routes.inventory_sources import _list_microsoft_workbooks

    ms, _ = stub_oauth
    ms.token = None
    result = asyncio_run(_list_microsoft_workbooks(session=None, company_id=1))
    assert result == {"connected": False, "files": [], "error": None}


def test_microsoft_search_filters_and_dedupes(stub_oauth, monkeypatch):
    from routes.inventory_sources import _list_microsoft_workbooks

    monkeypatch.setattr(
        "routes.inventory_sources.logger",
        types.SimpleNamespace(warning=lambda *a, **k: None),
    )
    _SCRIPTED_RESPONSES[:] = [
        # xlsx search — one spreadsheet, one non-spreadsheet, one folder, one dup id
        _FakeResponse(200, {
            "value": [
                {"id": "A1", "name": "stock.xlsx", "webUrl": "https://1drv.ms/A1", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}},
                {"id": "A2", "name": "notes.docx", "webUrl": "https://1drv.ms/A2", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}},
                {"id": "A3", "name": "folder", "webUrl": "https://1drv.ms/A3", "folder": {"childCount": 2}},
                {"id": "A1", "name": "stock.xlsx", "webUrl": "https://1drv.ms/A1", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}},
            ]
        }),
        # xls search — a .xls spreadsheet
        _FakeResponse(200, {
            "value": [
                {"id": "B1", "name": "legacy.xls", "webUrl": "https://onedrive.live.com/B1", "file": {"mimeType": "application/vnd.ms-excel"}},
            ]
        }),
        # csv search — API error (500), ignored
        _FakeResponse(500, text="boom"),
    ]
    result = asyncio_run(_list_microsoft_workbooks(session=None, company_id=1))
    assert result["connected"] is True
    assert result["error"] is None
    assert [f["id"] for f in result["files"]] == ["A1", "B1"]
    assert result["files"][0]["name"] == "stock.xlsx"
    assert result["files"][1]["url"] == "https://onedrive.live.com/B1"


def test_microsoft_search_not_supported_falls_back_to_drive_walk(stub_oauth, monkeypatch):
    from routes.inventory_sources import _list_microsoft_workbooks

    monkeypatch.setattr(
        "routes.inventory_sources.logger",
        types.SimpleNamespace(warning=lambda *a, **k: None),
    )
    _SCRIPTED_RESPONSES[:] = [
        # Personal OneDrive: search is notSupported for all three extensions.
        _FakeResponse(501, text="notSupported"),
        _FakeResponse(501, text="notSupported"),
        _FakeResponse(501, text="notSupported"),
        # Fallback walk: root children -> one spreadsheet + one folder.
        _FakeResponse(200, {
            "value": [
                {"id": "R1", "name": "Voice Call.xlsx", "webUrl": "https://1drv.ms/R1", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}},
                {"id": "R2", "name": "My Folder", "webUrl": "https://1drv.ms/R2", "folder": {"childCount": 1}},
                {"id": "R3", "name": "notes.docx", "webUrl": "https://1drv.ms/R3", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}},
            ]
        }),
        # Folder children -> a csv.
        _FakeResponse(200, {
            "value": [
                {"id": "F1", "name": "prices.csv", "webUrl": "https://1drv.ms/F1", "file": {"mimeType": "text/csv"}},
            ]
        }),
    ]
    result = asyncio_run(_list_microsoft_workbooks(session=None, company_id=1))
    assert result["connected"] is True
    assert result["error"] is None
    ids = [f["id"] for f in result["files"]]
    assert ids == ["R1", "F1"]
    assert result["files"][0]["name"] == "Voice Call.xlsx"
    assert result["files"][1]["name"] == "prices.csv"


def test_microsoft_401_forces_refresh_and_retries(stub_oauth, monkeypatch):
    from routes.inventory_sources import _list_microsoft_workbooks

    monkeypatch.setattr(
        "routes.inventory_sources.logger",
        types.SimpleNamespace(warning=lambda *a, **k: None),
    )
    _SCRIPTED_RESPONSES[:] = [
        _FakeResponse(401, text="expired"),
        _FakeResponse(200, {
            "value": [
                {"id": "C1", "name": "prices.xlsx", "webUrl": "https://1drv.ms/C1", "file": {"mimeType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}},
            ]
        }),
    ]
    ms, _ = stub_oauth
    result = asyncio_run(_list_microsoft_workbooks(session=None, company_id=1))
    assert ms.refreshed is True
    assert result["connected"] is True
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "prices.xlsx"


def test_zoho_not_connected_returns_connected_false(stub_oauth):
    from routes.inventory_sources import _list_zoho_workbooks

    _, zoho = stub_oauth
    zoho.token = None
    result = asyncio_run(_list_zoho_workbooks(session=None, company_id=1))
    assert result == {"connected": False, "files": [], "error": None}


def test_zoho_workbook_list_maps_files(stub_oauth):
    from routes.inventory_sources import _list_zoho_workbooks

    _SCRIPTED_RESPONSES[:] = [
        _FakeResponse(200, {
            "workbooks": [
                {"resource_id": "wb111", "workbook_name": "StockBook"},
                {"resource_id": "wb222", "workbook_name": "Customers"},
                {"no_resource": "skip-me"},
            ]
        }),
    ]
    result = asyncio_run(_list_zoho_workbooks(session=object(), company_id=1))
    assert result["connected"] is True
    assert result["error"] is None
    assert [f["id"] for f in result["files"]] == ["wb111", "wb222"]
    assert result["files"][0] == {
        "id": "wb111",
        "name": "StockBook",
        "url": "https://workdrive.zohopublic.com/sheet/open/wb111",
    }
    assert result["files"][1]["name"] == "Customers"


def test_zoho_401_forces_refresh_and_retries(stub_oauth, monkeypatch):
    from routes.inventory_sources import _list_zoho_workbooks

    monkeypatch.setattr(
        "routes.inventory_sources.logger",
        types.SimpleNamespace(warning=lambda *a, **k: None),
    )
    _SCRIPTED_RESPONSES[:] = [
        _FakeResponse(401, text="expired"),
        _FakeResponse(200, {"workbooks": [{"resource_id": "wb333", "workbook_name": "Prices"}]}),
    ]
    _, zoho = stub_oauth
    result = asyncio_run(_list_zoho_workbooks(session=object(), company_id=1))
    assert zoho.refreshed is True
    assert result["connected"] is True
    assert len(result["files"]) == 1
    assert result["files"][0]["name"] == "Prices"


def asyncio_run(coro):
    import asyncio
    return asyncio.new_event_loop().run_until_complete(coro)
