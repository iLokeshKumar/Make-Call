from __future__ import annotations

import asyncio
import logging

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from services.rag.query_engine import search as rag_search
from sqlmodel import Session

logger = logging.getLogger(__name__)


async def search_knowledge_base(
    query: str,
    company_id: int,
    collection: str = "all",
    n_results: int = 5,
) -> dict:
    def _sync() -> list[dict]:
        token = rls_company_id.set(company_id)
        try:
            return rag_search(query, company_id, collection=collection, n_results=n_results)
        finally:
            rls_company_id.reset(token)

    try:
        results = await asyncio.to_thread(_sync)
        return ToolResult.ok(results).model_dump()
    except Exception as exc:
        logger.error("[MCP:search_knowledge_base] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Knowledge search failed: {exc}",
            next_suggestion="Try a broader query or check that the knowledge base has been populated.",
        ).model_dump()


async def get_objection_rebuttal(company_id: int, limit: int = 12) -> dict:
    from services.objection_service import get_objection_playbook

    def _sync() -> str:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                return get_objection_playbook(session, company_id, limit=limit)
        finally:
            rls_company_id.reset(token)

    try:
        playbook = await asyncio.to_thread(_sync)
        return ToolResult.ok({"playbook": playbook}).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_objection_rebuttal] company=%s error=%s", company_id, exc)
        return ToolResult.fail(
            f"Objection lookup failed: {exc}",
            next_suggestion="Handle the objection conversationally or search_knowledge_base with the objection text.",
        ).model_dump()


async def get_competitor_intel(
    competitor_name: str,
    company_id: int,
    n_results: int = 5,
) -> dict:
    def _sync() -> list[dict]:
        token = rls_company_id.set(company_id)
        try:
            return rag_search(
                competitor_name,
                company_id,
                collection="competitors",
                n_results=n_results,
            )
        finally:
            rls_company_id.reset(token)

    try:
        results = await asyncio.to_thread(_sync)
        return ToolResult.ok(results).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_competitor_intel] company=%s competitor=%s error=%s", company_id, competitor_name, exc)
        return ToolResult.fail(
            f"Competitor intel lookup failed: {exc}",
            next_suggestion="Try search_knowledge_base with a broader query about the competitor.",
        ).model_dump()
