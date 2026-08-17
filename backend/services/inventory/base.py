"""Abstract base class for inventory providers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional


class InventoryProvider(ABC):
    priority: int = 100

    @abstractmethod
    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        """Return a dict with sku, name, stock, price, currency or None if not found."""

    @abstractmethod
    async def search(self, query: str) -> list[dict]:
        """Return matching products as a list of dicts."""

    @abstractmethod
    async def reserve(self, sku: str, qty: int) -> bool:
        """Decrement stock by qty. Return True on success, False if insufficient."""
