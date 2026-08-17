"""
orchestrator.py - InventoryService: tries providers in priority order, returns first result.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.inventory.base import InventoryProvider

logger = logging.getLogger(__name__)


class InventoryService:
    def __init__(self, providers: list[InventoryProvider]):
        self._providers = sorted(providers, key=lambda p: p.priority, reverse=True)

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        for provider in self._providers:
            pname = type(provider).__name__
            logger.info("[inventory] lookup sku=%r via %s (priority=%s)", sku, pname, provider.priority)
            result = await provider.lookup(sku, location)
            if result:
                logger.info("[inventory] lookup HIT from %s: %s", pname, result)
                return result
            logger.info("[inventory] lookup MISS from %s", pname)
        logger.warning("[inventory] lookup: no provider found sku=%r", sku)
        return None

    async def search(self, query: str) -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []
        for provider in self._providers:
            pname = type(provider).__name__
            hits = await provider.search(query)
            logger.info("[inventory] search q=%r via %s → %d result(s)", query, pname, len(hits))
            for item in hits:
                key = item.get("sku", item.get("name", ""))
                if key not in seen:
                    seen.add(key)
                    results.append(item)
        logger.info("[inventory] search q=%r total=%d unique result(s)", query, len(results))
        return results

    async def reserve(self, sku: str, qty: int) -> bool:
        for provider in self._providers:
            if await provider.reserve(sku, qty):
                logger.info("[inventory] reserve sku=%r qty=%d via %s — OK", sku, qty, type(provider).__name__)
                return True
        logger.warning("[inventory] reserve sku=%r qty=%d — no provider could fulfil", sku, qty)
        return False
