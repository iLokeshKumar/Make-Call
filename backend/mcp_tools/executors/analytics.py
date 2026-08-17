from __future__ import annotations

import asyncio
import logging

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session

logger = logging.getLogger(__name__)


async def get_pipeline_funnel(company_id: int, scope_user_id: int | None = None) -> dict:
    from services.analytics.analytics_service import get_pipeline_funnel as svc_funnel

    def _sync() -> list[dict]:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return svc_funnel(session, company_id, scope_user_id=scope_user_id)
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_pipeline_funnel] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Pipeline funnel query failed: {exc}",
            next_suggestion="Try get_engagement_summary for activity metrics instead.",
        ).model_dump()


async def get_engagement_summary(
    company_id: int,
    lookback_days: int = 30,
    scope_user_id: int | None = None,
) -> dict:
    from services.analytics.analytics_service import get_engagement_summary as svc_engagement

    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return svc_engagement(
                    session,
                    company_id,
                    lookback_days=lookback_days,
                    scope_user_id=scope_user_id,
                )
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_engagement_summary] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Engagement summary query failed: {exc}",
            next_suggestion="Try get_pipeline_funnel for pipeline stage data instead.",
        ).model_dump()
