"""
orchestrator.py - InventoryService: tries providers in priority order, returns first result.
"""
from __future__ import annotations

from typing import Optional

from services.inventory.base import InventoryProvider


class InventoryService:
    def __init__(self, providers: list[InventoryProvider]):
        self._providers = sorted(providers, key=lambda p: p.priority, reverse=True)

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        for provider in self._providers:
            result = await provider.lookup(sku, location)
            if result:
                return result
        return None

    async def search(self, query: str) -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []
        for provider in self._providers:
            for item in await provider.search(query):
                key = item.get("sku", item.get("name", ""))
                if key not in seen:
                    seen.add(key)
                    results.append(item)
        return results

    async def reserve(self, sku: str, qty: int) -> bool:
        for provider in self._providers:
            if await provider.reserve(sku, qty):
                return True
        return False
