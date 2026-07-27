"""
factory.py - Build an InventoryService for a company from its configured sources.

The DbProductProvider (wrapping the existing Product table) is always included
as the base layer. Additional InventorySource rows layer on top.
"""
from __future__ import annotations

from sqlmodel import Session, select

from models.inventory_source import InventorySource
from services.inventory.base import InventoryProvider
from services.inventory.db_product_provider import DbProductProvider
from services.inventory.orchestrator import InventoryService


def _make_provider(source: InventorySource, session: Session, company_id: int) -> InventoryProvider | None:
    if source.source_type == "csv":
        from services.inventory.csv_provider import CsvInventoryProvider
        return CsvInventoryProvider(config=source.config_json, priority=source.priority)
    # google_sheets, erp_api, manual — stubs for future providers
    return None


async def build_inventory_service(session: Session, company_id: int) -> InventoryService:
    """Instantiate all enabled providers for a company and return the orchestrator."""
    providers: list[InventoryProvider] = [
        DbProductProvider(session=session, company_id=company_id, priority=100)
    ]
    sources = list(session.exec(
        select(InventorySource).where(
            InventorySource.company_id == company_id,
            InventorySource.enabled == True,
        ).order_by(InventorySource.priority.desc())
    ).all())
    for source in sources:
        if source.source_type == "db_product":
            continue  # already added as default above
        provider = _make_provider(source, session, company_id)
        if provider:
            providers.append(provider)
    return InventoryService(providers)
