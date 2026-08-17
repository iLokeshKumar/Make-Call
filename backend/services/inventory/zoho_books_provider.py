"""Inventory provider backed by the Zoho Books Items API."""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

from services.inventory.base import InventoryProvider

logger = logging.getLogger(__name__)


class ZohoBooksProvider(InventoryProvider):
    def __init__(self, config: dict, priority: int = 80, session=None, company_id: int | None = None):
        self.priority = priority
        self.config = config
        self.session = session
        self.company_id = company_id
        self.organization_id = str(config.get("organization_id") or config.get("org_id") or os.getenv("ZOHO_BOOKS_ORG_ID") or "").strip()
        self._cache: list[dict] | None = None

    def _token(self, force_refresh: bool = False) -> str | None:
        if not self.session or not self.company_id:
            return None
        from agents.f3_books_sync import _get_books_token
        try:
            return _get_books_token(self.session, self.company_id, force_refresh=force_refresh)
        except Exception:
            return None

    async def test_connection(self) -> dict:
        """Verify the connection without loading the full catalog.

        Fetches the first page of items and reports the count. Raises a
        ValueError with a user-actionable message when the token is missing,
        the organization ID is invalid, or Zoho rejects the request — so the
        UI can show exactly what to fix.
        """
        token = self._token()
        if not token:
            raise ValueError("Zoho Books is not connected. Reconnect Zoho with the ZohoBooks.fullaccess.all scope in Settings → Connectors.")
        if not self.organization_id:
            raise ValueError("Enter the Zoho Books organization ID first.")

        async def _fetch(_token: str) -> httpx.Response:
            async with httpx.AsyncClient(timeout=30) as client:
                return await client.get(
                    "https://www.zohoapis.com/books/v3/items",
                    headers={"Authorization": f"Zoho-oauthtoken {_token}"},
                    params={"organization_id": self.organization_id, "page": 1, "per_page": 200},
                )

        response = await _fetch(token)
        if response.status_code == 401:
            refreshed = self._token(force_refresh=True)
            if refreshed and refreshed != token:
                token = refreshed
                response = await _fetch(token)
            else:
                raise ValueError("Zoho Books connection expired — reconnect Zoho in Settings → Connectors.")
        if response.status_code >= 400:
            try:
                data = response.json()
            except Exception:
                data = None
            zoho_message = ""
            if isinstance(data, dict):
                zoho_message = str(data.get("message") or data.get("error") or "")
            if "invalid_org" in zoho_message.lower() or "INVALID_ORG" in zoho_message.upper():
                raise ValueError("Zoho Books rejected this organization ID — double-check it under Zoho Books → Settings → Organization Profile.")
            if response.status_code == 401 or "auth" in zoho_message.lower():
                raise ValueError("Zoho Books authentication failed — reconnect Zoho with the ZohoBooks.fullaccess.all scope.")
            raise ValueError(
                f"Zoho Books API error (HTTP {response.status_code}). "
                f"{zoho_message} Check the organization ID and Zoho connection.".strip()
            )
        try:
            data = response.json()
        except Exception:
            raise ValueError("Zoho Books returned an unreadable response.")
        items = data.get("items") or []
        return {
            "ok": True,
            "item_count": len(items),
            "has_more_page": bool((data.get("page_context") or {}).get("has_more_page")),
            "organization_id": self.organization_id,
        }

    async def _rows(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        token = self._token()
        if not token:
            raise ValueError("Zoho Books is not connected. Reconnect Zoho with ZohoBooks.fullaccess.all scope.")
        if not self.organization_id:
            raise ValueError("Zoho Books organization ID is required.")

        rows: list[dict] = []
        async with httpx.AsyncClient(timeout=30) as client:
            for page in range(1, 51):
                response = await client.get(
                    "https://www.zohoapis.com/books/v3/items",
                    headers={"Authorization": f"Zoho-oauthtoken {token}"},
                    params={"organization_id": self.organization_id, "page": page, "per_page": 200},
                )
                if response.status_code == 401:
                    # Stale/revoked token slipped past the expiry check — force
                    # one refresh and retry this page before surfacing an error.
                    refreshed = self._token(force_refresh=True)
                    if refreshed and refreshed != token:
                        token = refreshed
                        response = await client.get(
                            "https://www.zohoapis.com/books/v3/items",
                            headers={"Authorization": f"Zoho-oauthtoken {token}"},
                            params={"organization_id": self.organization_id, "page": page, "per_page": 200},
                        )
                    else:
                        raise ValueError(
                            "Zoho Books connection expired — reconnect Zoho in Settings to read the inventory."
                        )
                response.raise_for_status()
                data = response.json()
                page_rows = data.get("items") or []
                rows.extend(page_rows)
                if not data.get("page_context", {}).get("has_more_page") or len(page_rows) < 200:
                    break

        self._cache = [{
            "sku": item.get("sku") or item.get("item_id"),
            "name": item.get("name") or item.get("item_name"),
            "stock": item.get("stock_on_hand", item.get("available_stock", 0)),
            "price": item.get("rate", item.get("purchase_rate")),
            "currency": item.get("currency_code"),
            "category": item.get("category_name"),
            "brand": item.get("brand"),
            "description": item.get("description"),
            "source": "zoho_books",
            "zoho_item_id": item.get("item_id"),
        } for item in rows]
        logger.info("ZohoBooksProvider: loaded %d items company=%s", len(self._cache), self.company_id)
        return self._cache

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        wanted = sku.strip().lower()
        return next((row for row in await self._rows() if str(row.get("sku") or "").strip().lower() == wanted), None)

    async def search(self, query: str) -> list[dict]:
        q = query.lower().strip()
        fields = ("name", "sku", "brand", "category", "description")
        return [row for row in await self._rows() if any(q in str(row.get(f) or "").lower() for f in fields)][:20]

    async def reserve(self, sku: str, qty: int) -> bool:
        return False
