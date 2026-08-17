from __future__ import annotations

import json
import sys
import types

import pytest

from services.inventory.zoho_books_provider import ZohoBooksProvider


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, headers: dict | None = None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def json(self):
        return json.loads(self.content.decode("utf-8"))


class _FakeAsyncClient:
    urls: list[str] = []
    responses: dict[str, tuple[int, bytes]] = {}

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url: str, headers: dict | None = None, params: dict | None = None) -> _FakeResponse:
        del headers, params
        self.urls.append(url)
        status, content = self.responses.get(url, (404, b""))
        return _FakeResponse(content, status)


def _install_token_stub(monkeypatch: pytest.MonkeyPatch, token: str | None = "fake-books-token") -> None:
    """Stub agents.f3_books_sync._get_books_token so the provider never hits DB/encryption."""
    agents_mod = types.ModuleType("agents")
    f3_mod = types.ModuleType("agents.f3_books_sync")
    f3_mod._get_books_token = lambda session, company_id, force_refresh=False: token
    monkeypatch.setitem(sys.modules, "agents", agents_mod)
    monkeypatch.setitem(sys.modules, "agents.f3_books_sync", f3_mod)


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.urls = []
    _FakeAsyncClient.responses = {}
    yield
    _FakeAsyncClient.urls = []
    _FakeAsyncClient.responses = {}


ITEMS_URL = "https://www.zohoapis.com/books/v3/items"


def _items_body(count: int = 3, has_more: bool = False) -> bytes:
    return json.dumps({
        "items": [{"item_id": f"it{i}", "name": f"Item {i}", "sku": f"SKU-{i}", "stock_on_hand": i, "rate": 10 + i} for i in range(count)],
        "page_context": {"has_more_page": has_more},
    }).encode()


async def test_connection_success_returns_item_count(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token_stub(monkeypatch)
    provider_mod_httpx = __import__("httpx")
    import services.inventory.zoho_books_provider as books_provider_mod
    monkeypatch.setattr(books_provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {ITEMS_URL: (200, _items_body(count=5))}

    provider = ZohoBooksProvider(config={"organization_id": "60012345678"}, session=object(), company_id=1)
    result = await provider.test_connection()

    assert result["ok"] is True
    assert result["item_count"] == 5
    assert result["has_more_page"] is False
    assert result["organization_id"] == "60012345678"
    assert _FakeAsyncClient.urls == [ITEMS_URL]


async def test_connection_success_with_more_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token_stub(monkeypatch)
    import services.inventory.zoho_books_provider as books_provider_mod
    monkeypatch.setattr(books_provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {ITEMS_URL: (200, _items_body(count=200, has_more=True))}

    provider = ZohoBooksProvider(config={"organization_id": "60012345678"}, session=object(), company_id=1)
    result = await provider.test_connection()

    assert result["ok"] is True
    assert result["item_count"] == 200
    assert result["has_more_page"] is True


async def test_connection_raises_for_invalid_org_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token_stub(monkeypatch)
    import services.inventory.zoho_books_provider as books_provider_mod
    monkeypatch.setattr(books_provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {
        ITEMS_URL: (400, json.dumps({"code": 1001, "message": "INVALID_ORG_ID"}).encode()),
    }

    provider = ZohoBooksProvider(config={"organization_id": "wrong-org"}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider.test_connection()

    assert "organization ID" in str(excinfo.value)


async def test_connection_raises_for_auth_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token_stub(monkeypatch)
    import services.inventory.zoho_books_provider as books_provider_mod
    monkeypatch.setattr(books_provider_mod.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.responses = {
        ITEMS_URL: (401, json.dumps({"code": 1001, "message": "INVALID_TOKEN"}).encode()),
    }

    provider = ZohoBooksProvider(config={"organization_id": "60012345678"}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider.test_connection()

    assert "expired" in str(excinfo.value) or "auth" in str(excinfo.value).lower()


async def test_connection_raises_when_not_connected(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token_stub(monkeypatch, token=None)
    provider = ZohoBooksProvider(config={"organization_id": "60012345678"}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider.test_connection()

    assert "not connected" in str(excinfo.value)


async def test_connection_raises_without_org_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token_stub(monkeypatch)
    provider = ZohoBooksProvider(config={}, session=object(), company_id=1)
    with pytest.raises(ValueError) as excinfo:
        await provider.test_connection()

    assert "organization ID" in str(excinfo.value)
