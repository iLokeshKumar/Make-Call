from __future__ import annotations

import asyncio
import logging

from database import engine, rls_company_id
from models.models import Product
from schemas.tool_result import ToolResult
from sqlmodel import Session, select

logger = logging.getLogger(__name__)


async def get_product_info(product_name: str, company_id: int) -> dict:
    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                stmt = (
                    select(Product)
                    .where(
                        Product.company_id == company_id,
                        Product.is_active == True,  # noqa: E712
                        Product.name.ilike(f"%{product_name}%"),
                    )
                    .limit(1)
                )
                product = session.exec(stmt).first()
                if not product:
                    return {}
                return {
                    "id": product.id,
                    "name": product.name,
                    "sku": product.sku,
                    "description": product.description,
                    "price": float(product.price),
                    "mrp": float(product.mrp) if product.mrp is not None else None,
                    "stock_count": product.stock,
                    "category": product.category,
                    "brand": product.brand,
                    "currency": product.currency,
                    "is_active": product.is_active,
                }
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        if not data:
            return ToolResult.fail(
                f"No active product matching '{product_name}' found.",
                next_suggestion="Try a shorter product name or check the catalog with a broader search.",
            ).model_dump()
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_product_info] company=%s product=%s error=%s", company_id, product_name, exc)
        return ToolResult.fail(
            f"Product lookup failed: {exc}",
            next_suggestion="Try sync_product_catalog if the catalog may be out of date.",
        ).model_dump()


async def create_quote_for_lead(
    lead_id: int,
    company_id: int,
    user_id: int,
    items: list[dict],
    notes: str = "",
    send_email: bool = False,
) -> dict:
    """items = [{product_id, quantity, discount_percent?}]"""
    from services.quote.quote_service import create_quote

    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                quote = create_quote(
                    session=session,
                    company_id=company_id,
                    lead_id=lead_id,
                    actor_user_id=user_id,
                    items=items,
                    notes=notes,
                    send_email=send_email,
                )
                return {
                    "quote_id": quote.id,
                    "quote_number": quote.quote_number,
                    "total_amount": float(quote.total_amount),
                    "status": quote.status,
                }
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:create_quote_for_lead] lead=%s error=%s", lead_id, exc)
        return ToolResult.fail(
            f"Quote creation failed: {exc}",
            next_suggestion="Verify the lead_id exists and all product_ids are valid.",
        ).model_dump()


async def sync_product_catalog(company_id: int, user_id: int) -> dict:
    from services.platform.integration_service import trigger_inventory_sync

    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return trigger_inventory_sync(session, company_id, user_id)
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:sync_product_catalog] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Catalog sync failed: {exc}",
            next_suggestion="Check that an inventory source (Zoho Books, CSV) has been configured in Settings > Integrations.",
        ).model_dump()
