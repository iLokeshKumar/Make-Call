"""
db_product_provider.py - Inventory provider that reads from the existing Product table.

This is the default source for every company — no InventorySource row required.
Product.sku is the primary lookup key; Product.stock is the authoritative quantity.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import Session, select

from models.models import Product
from services.inventory.base import InventoryProvider


def _to_dict(p: Product) -> dict:
    return {
        "sku": p.sku or str(p.id),
        "name": p.name,
        "stock": p.stock,
        "price": float(p.price),
        "currency": p.currency,
        "category": p.category,
        "brand": p.brand,
        "description": p.description,
        "source": "db_product",
    }


class DbProductProvider(InventoryProvider):
    def __init__(self, session: Session, company_id: int, priority: int = 100):
        self.session = session
        self.company_id = company_id
        self.priority = priority

    async def lookup(self, sku: str, location: Optional[str] = None) -> Optional[dict]:
        product = self.session.exec(
            select(Product).where(
                Product.company_id == self.company_id,
                Product.sku == sku,
                Product.is_active == True,
            )
        ).first()
        return _to_dict(product) if product else None

    async def search(self, query: str) -> list[dict]:
        results = self.session.exec(
            select(Product).where(
                Product.company_id == self.company_id,
                Product.is_active == True,
                Product.name.icontains(query),
            ).limit(20)
        ).all()
        return [_to_dict(p) for p in results]

    async def reserve(self, sku: str, qty: int) -> bool:
        product = self.session.exec(
            select(Product).where(
                Product.company_id == self.company_id,
                Product.sku == sku,
                Product.is_active == True,
            )
        ).first()
        if not product or product.stock < qty:
            return False
        product.stock -= qty
        self.session.add(product)
        self.session.commit()
        return True
