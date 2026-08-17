"""
csv_provider.py - Inventory provider that reads from a CSV file.

Config fields expected in InventorySource.config_json:
  file_path  — absolute or relative path to the CSV file
  sku_col    — column name for SKU (default: "sku")
  name_col   — column name for product name (default: "name")
  stock_col  — column name for stock quantity (default: "stock")
  price_col  — column name for price (default: "price")
  currency   — fixed currency code (default: "INR")
"""
from __future__ import annotations

import csv
import logging
import os
from typing import Optional

from services.inventory.base import InventoryProvider

logger = logging.getLogger(__name__)


class CsvInventoryProvider(InventoryProvider):
    def __init__(self, config: dict, priority: int = 80):
        self.file_path = config.get("file_path", "")
        self.sku_col = config.get("sku_col", "sku")
        self.name_col = config.get("name_col", "name")
        self.stock_col = config.get("stock_col", "stock")
        self.price_col = config.get("price_col", "price")
        self.currency = config.get("currency", "INR")
        self.priority = priority
        self._rows: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._rows is not None:
            return self._rows
        if not self.file_path or not os.path.exists(self.file_path):
            logger.warning("[csv_provider] File not found: %s", self.file_path)
            self._rows = []
            return self._rows
        with open(self.file_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self._rows = list(reader)
        return self._rows

    def _to_dict(self, row: dict) -> dict:
        return {
            "sku": row.get(self.sku_col, ""),
            "name": row.get(self.name_col, ""),
            "stock": int(row.get(self.stock_col, 0) or 0),
            "price": float(row.get(self.price_col, 0) or 0),
            "currency": self.currency,
            "source": "csv",
        }

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        for row in self._load():
            if row.get(self.sku_col, "").strip().lower() == sku.strip().lower():
                return self._to_dict(row)
        return None

    async def search(self, query: str) -> list[dict]:
        q = query.lower()
        return [
            self._to_dict(row) for row in self._load()
            if q in row.get(self.name_col, "").lower()
            or q in row.get(self.sku_col, "").lower()
        ][:20]

    async def reserve(self, sku: str, qty: int) -> bool:
        # CSV is read-only — reservation not supported
        return False
