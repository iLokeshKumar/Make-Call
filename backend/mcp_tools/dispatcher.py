"""
ToolDispatcher — the smart routing brain for Rio CRM tool calls.

Routing chain (each layer falls through to the next on miss):
  1. direct  — tool_name is known → look up executor in registry → run it
  2. keyword  — fast keyword match via ToolRouter
  3. semantic — embedding cosine similarity against all tool descriptions
  4. error    — no match → fail with available tool list

Usage:
    dispatcher = ToolDispatcher.get()
    result = await dispatcher.dispatch("score_lead", {"lead_id": 42}, company_id=1)
    result = await dispatcher.route_intent("which channel should I use?", company_id=1, lead_id=42)
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import Any, Optional

from mcp_tools.tool_catalog import tool_names_for_company
from schemas.tool_result import ToolResult

logger = logging.getLogger(__name__)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(x * x for x in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


async def _trace(
    tool_name: str,
    company_id: int,
    status: str,
    duration_ms: int,
    user_id: Optional[int],
    interaction_id: Optional[int],
    error_message: Optional[str],
) -> None:
    try:
        from services.observability.tool_call_tracer import trace_tool_call
        await trace_tool_call(
            tool_name=tool_name,
            company_id=company_id,
            status=status,
            duration_ms=duration_ms,
            user_id=user_id,
            interaction_id=interaction_id,
            error_message=error_message,
        )
    except Exception as exc:
        logger.debug("[Dispatcher] trace failed silently: %s", exc)


class ToolDispatcher:
    """
    Singleton dispatcher. Holds the ToolRegistry and an embedding cache
    for semantic routing. Initialize once at startup via ToolDispatcher.get().
    """

    _instance: "ToolDispatcher | None" = None

    def __init__(self, registry) -> None:
        self.registry = registry
        # tool_name → embedding vector (populated lazily on first semantic route)
        self._desc_embeddings: dict[str, list[float]] = {}

    @classmethod
    def get(cls) -> "ToolDispatcher":
        """Return the process-wide singleton, creating it if needed."""
        if cls._instance is None:
            from mcp_tools.registry import ToolRegistry
            from mcp_tools.registration import populate
            r = ToolRegistry()
            populate(r)
            cls._instance = cls(r)
        return cls._instance

    # ─── public API ───────────────────────────────────────────────────────────

    async def dispatch(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        company_id: int,
        user_id: Optional[int] = None,
        interaction_id: Optional[int] = None,
    ) -> dict:
        """
        Direct dispatch: the LLM (or caller) already knows which tool to call.
        Validates company access, resolves the executor, injects company_id,
        runs the executor, and fires a background trace.
        """
        start = time.monotonic()
        status = "success"
        error_msg: Optional[str] = None

        try:
            # 1. Validate the tool exists in registry
            all_registered = self.registry.list_all()
            if tool_name not in all_registered:
                return ToolResult.fail(
                    f"Tool '{tool_name}' is not registered.",
                    next_suggestion=f"Available tools: {', '.join(sorted(all_registered)[:8])}...",
                ).model_dump()

            # 2. Validate company has access
            enabled = tool_names_for_company(company_id)
            if tool_name not in enabled:
                return ToolResult.fail(
                    f"Tool '{tool_name}' is not enabled for this company.",
                    next_suggestion="Enable the required integration in Settings → MCP Connections.",
                ).model_dump()

            # 3. Build call args — inject company_id/user_id if not supplied
            call_args = dict(arguments)
            if "company_id" not in call_args:
                call_args["company_id"] = company_id
            if user_id is not None and "actor_user_id" not in call_args and "user_id" not in call_args:
                call_args["actor_user_id"] = user_id

            # 4. Execute
            executor = self.registry.get_executor(tool_name)
            result = await executor(**call_args)

            if isinstance(result, dict) and not result.get("success", True):
                status = "error"
                error_msg = result.get("error")

            return result

        except Exception as exc:
            status = "error"
            error_msg = str(exc)
            logger.error("[Dispatcher] %s raised: %s", tool_name, exc)
            return ToolResult.fail(f"{tool_name} raised an unexpected error: {exc}").model_dump()

        finally:
            dur_ms = int((time.monotonic() - start) * 1000)
            asyncio.create_task(
                _trace(tool_name, company_id, status, dur_ms, user_id, interaction_id, error_msg)
            )

    async def route_intent(
        self,
        query: str,
        company_id: int,
        user_id: Optional[int] = None,
        interaction_id: Optional[int] = None,
        **extra_args: Any,
    ) -> dict:
        """
        Intent-based dispatch for free-form natural language queries.
        Tries keyword routing first, then falls back to semantic similarity.
        """
        # Layer 1: keyword routing
        try:
            from mcp_tools.router import ToolRouter
            router = ToolRouter(self.registry)
            decision = router.route(query)
            enabled = tool_names_for_company(company_id)
            for tool_name in (decision.tools if hasattr(decision, "tools") else []):
                if tool_name in enabled and tool_name in self.registry.list_all():
                    return await self.dispatch(
                        tool_name, extra_args, company_id, user_id, interaction_id
                    )
        except Exception as exc:
            logger.debug("[Dispatcher] keyword routing error: %s", exc)

        # Layer 2: semantic routing
        return await self._semantic_dispatch(
            query, company_id, user_id, interaction_id, **extra_args
        )

    def get_available_tools(self, company_id: int) -> list[dict]:
        """
        Return Mistral-compatible tool schemas for this company's enabled tools.
        Merges legacy tool_adapter schemas with the registry's generated schemas.
        """
        try:
            from tool_adapter import get_mistral_tools
            return get_mistral_tools(company_id)
        except Exception as exc:
            logger.warning("[Dispatcher] get_available_tools fallback: %s", exc)
            return []

    def build_tool_context_string(self, company_id: int) -> str:
        """
        One-line-per-tool summary for injection into system prompts.
        Only includes tools that are both registered and enabled for this company.
        """
        enabled = tool_names_for_company(company_id)
        registered = self.registry.list_all()
        lines: list[str] = []
        for tool_name in sorted(enabled & set(registered)):
            spec = self.registry.get_spec(tool_name)
            if spec:
                first_sentence = spec.description.split(".")[0].strip()
                lines.append(f"• {tool_name}: {first_sentence}")
        return "\n".join(lines) if lines else "No tools registered for this company."

    # ─── internal ─────────────────────────────────────────────────────────────

    async def _semantic_dispatch(
        self,
        query: str,
        company_id: int,
        user_id: Optional[int],
        interaction_id: Optional[int],
        **extra_args: Any,
    ) -> dict:
        enabled = tool_names_for_company(company_id)
        candidates = [t for t in self.registry.list_all() if t in enabled]

        if not candidates:
            return ToolResult.fail(
                "No tools are enabled for this company.",
                next_suggestion="Configure integrations in Settings → MCP Connections.",
            ).model_dump()

        try:
            from services.rag.embeddings import embed
            query_vec: list[float] = await asyncio.to_thread(embed, query)
        except Exception as exc:
            logger.warning("[Dispatcher] embedding unavailable, listing tools: %s", exc)
            return ToolResult.fail(
                f"Could not match '{query}' to a tool (embeddings unavailable).",
                next_suggestion=f"Available tools: {', '.join(sorted(candidates)[:10])}",
            ).model_dump()

        # Populate desc embedding cache for candidates
        await self._warm_desc_cache(candidates)

        best_tool: Optional[str] = None
        best_score = -1.0
        for tool_name in candidates:
            if tool_name not in self._desc_embeddings:
                continue
            score = _cosine(query_vec, self._desc_embeddings[tool_name])
            if score > best_score:
                best_score = score
                best_tool = tool_name

        SEMANTIC_THRESHOLD = 0.35
        if best_tool and best_score >= SEMANTIC_THRESHOLD:
            logger.info("[Dispatcher] semantic match: %s (score=%.3f)", best_tool, best_score)
            return await self.dispatch(
                best_tool, extra_args, company_id, user_id, interaction_id
            )

        return ToolResult.fail(
            f"No tool matched query '{query[:80]}' (best={best_score:.2f}).",
            next_suggestion=f"Try one of: {', '.join(sorted(candidates)[:8])}",
        ).model_dump()

    async def _warm_desc_cache(self, tool_names: list[str]) -> None:
        """Lazily embed tool descriptions (cached per process lifetime)."""
        missing = [t for t in tool_names if t not in self._desc_embeddings]
        if not missing:
            return
        try:
            from services.rag.embeddings import embed
            for tool_name in missing:
                spec = self.registry.get_spec(tool_name)
                if spec:
                    text = f"{spec.name}: {spec.description}"
                    vec = await asyncio.to_thread(embed, text)
                    self._desc_embeddings[tool_name] = vec
        except Exception as exc:
            logger.warning("[Dispatcher] desc cache warm failed: %s", exc)
