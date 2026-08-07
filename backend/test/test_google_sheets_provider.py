from __future__ import annotations

import csv
import io
import sys
import types

import pytest

from services.inventory import google_sheets_provider as gsheets


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200):
        self.content = content
        self.status_code = status_code
        self.text = content.decode()

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    urls: list[str] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url: str) -> _FakeResponse:
        self.urls.append(url)
        if url.endswith("/edit?usp=sharing"):
            return _FakeResponse(
                b'window.bootstrap = [{"name":"Lead","gid":"0"},{"name":"Inventory","gid":"987654321"}];'
            )
        if "sheet=Inventory" in url:
            return _FakeResponse(b"name,sku,stock\nOLED Monitor,MON-1,5\n")
        if "gid=987654321" in url:
            return _FakeResponse(b"name,sku,stock\nGID Monitor,MON-2,7\n")
        return _FakeResponse(b"lead,email\nAlice,alice@example.com\n")


def _install_product_parser_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    def _parse_product_file(content: bytes, filename: str, sheet_name: str | None = None) -> list[dict]:
        del filename, sheet_name
        reader = csv.DictReader(io.StringIO(content.decode()))
        return [row for row in reader if row.get("name")]

    routes_mod = types.ModuleType("routes")
    products_mod = types.ModuleType("routes.products")
    products_mod._parse_product_file = _parse_product_file
    monkeypatch.setitem(sys.modules, "routes", routes_mod)
    monkeypatch.setitem(sys.modules, "routes.products", products_mod)


@pytest.fixture(autouse=True)
def _clear_cache():
    gsheets._CACHE.clear()
    _FakeAsyncClient.urls = []
    yield
    gsheets._CACHE.clear()


def test_extracts_gid_from_google_sheet_fragment() -> None:
    url = "https://docs.google.com/spreadsheets/d/sheet123/edit?usp=sharing#gid=987654321"

    assert gsheets._extract_sheet_id(url) == "sheet123"
    assert gsheets._extract_gid(url) == "987654321"


def test_parse_public_sheet_tabs_from_google_page_html() -> None:
    html = 'window.bootstrap = [{"name":"Lead","gid":"0"},{"name":"Inventory","gid":"987654321"}];'

    assert gsheets._parse_public_sheet_tabs(html) == [
        {"name": "Lead", "gid": "0"},
        {"name": "Inventory", "gid": "987654321"},
    ]


@pytest.mark.asyncio
async def test_lists_public_worksheets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gsheets.httpx, "AsyncClient", _FakeAsyncClient)

    tabs = await gsheets.list_public_worksheets("https://docs.google.com/spreadsheets/d/sheet123/edit")

    assert tabs == [
        {"name": "Lead", "gid": "0"},
        {"name": "Inventory", "gid": "987654321"},
    ]


@pytest.mark.asyncio
async def test_auto_tries_inventory_sheet_before_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_product_parser_stub(monkeypatch)
    monkeypatch.setattr(gsheets.httpx, "AsyncClient", _FakeAsyncClient)
    provider = gsheets.GoogleSheetsProvider({"url": "https://docs.google.com/spreadsheets/d/sheet123/edit"})

    rows = await provider._rows()

    assert rows == [{"name": "OLED Monitor", "sku": "MON-1", "stock": "5"}]
    assert "sheet=Inventory" in _FakeAsyncClient.urls[0]
    assert all("export?format=csv" not in url for url in _FakeAsyncClient.urls)


@pytest.mark.asyncio
async def test_gid_in_pasted_url_is_used_directly(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_product_parser_stub(monkeypatch)
    monkeypatch.setattr(gsheets.httpx, "AsyncClient", _FakeAsyncClient)
    provider = gsheets.GoogleSheetsProvider(
        {"url": "https://docs.google.com/spreadsheets/d/sheet123/edit#gid=987654321"}
    )

    rows = await provider._rows()

    assert rows == [{"name": "GID Monitor", "sku": "MON-2", "stock": "7"}]
    assert _FakeAsyncClient.urls == [
        "https://docs.google.com/spreadsheets/d/sheet123/export?format=csv&gid=987654321"
    ]
