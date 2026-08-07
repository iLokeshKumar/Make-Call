"""
factory.py - Build an InventoryService for a company from its configured sources.

The DbProductProvider (wrapping the existing Product table) is always included
as the base layer. Additional InventorySource rows layer on top.
"""
from __future__ import annotations

import logging

from sqlmodel import Session, select

from models.inventory_source import InventorySource
from services.inventory.base import InventoryProvider
from services.inventory.db_product_provider import DbProductProvider
from services.inventory.orchestrator import InventoryService

logger = logging.getLogger(__name__)


def _make_provider(source: InventorySource, session: Session, company_id: int) -> InventoryProvider | None:
    if source.source_type == "csv":
        from services.inventory.csv_provider import CsvInventoryProvider
        return CsvInventoryProvider(config=source.config_json, priority=source.priority)
    if source.source_type == "google_sheets":
        from services.inventory.google_sheets_provider import GoogleSheetsProvider
        logger.info(
            "[inventory_factory] google_sheets config source_id=%s name=%r gid=%r sheet_name=%r has_url=%s",
            source.id,
            source.name,
            source.config_json.get("gid"),
            source.config_json.get("sheet_name"),
            bool(source.config_json.get("url")),
        )
        return GoogleSheetsProvider(config=source.config_json, priority=source.priority)
    logger.warning("[inventory_factory] Unsupported source_type '%s' (id=%s) — skipped", source.source_type, source.id)
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

    logger.info("[inventory_factory] company=%s — %d enabled source(s) in DB", company_id, len(sources))

    for source in sources:
        if source.source_type == "db_product":
            continue  # already added as default above
        provider = _make_provider(source, session, company_id)
        if provider:
            providers.append(provider)
            logger.info(
                "[inventory_factory] +provider: id=%s name=%r type=%s priority=%s enabled=%s",
                source.id,
                source.name,
                source.source_type,
                source.priority,
                source.enabled,
            )
        else:
            logger.warning("[inventory_factory] source '%s' (type=%s) produced no provider", source.name, source.source_type)

    logger.info("[inventory_factory] total providers: %s", [type(p).__name__ for p in providers])
    return InventoryService(providers)
