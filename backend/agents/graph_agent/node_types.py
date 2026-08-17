"""Node type implementations for graph-based conversation agents.

Each node type implements the execute() method which produces
audio/text output for the voice pipeline.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

from .models import GraphNode, GraphNodeRAGConfig

logger = logging.getLogger(__name__)


class NodeResult:
    """Result from executing a single graph node."""

    def __init__(
        self,
        text: str = "",
        is_final: bool = True,
        tool_calls: list[dict] | None = None,
        target_node_id: str | None = None,
        hangup: bool = False,
        hangup_reason: str | None = None,
        audio_data: bytes | None = None,
    ):
        self.text = text
        self.is_final = is_final
        self.tool_calls = tool_calls or []
        self.target_node_id = target_node_id
        self.hangup = hangup
        self.hangup_reason = hangup_reason
        self.audio_data = audio_data


class LLMNode:
    """A node that generates a response using the LLM.

    The node's prompt is combined with the global agent_information
    and sent to the LLM. Supports per-node RAG context injection
    and function calling.
    """

    def __init__(
        self,
        node: GraphNode,
        agent_information: str | None = None,
        llm_service=None,
        rag_service=None,
    ):
        self.node = node
        self.agent_information = agent_information or ""
        self.llm_service = llm_service
        self.rag_service = rag_service

    async def execute(
        self,
        transcript: str,
        context_data: dict | None = None,
    ) -> AsyncGenerator[NodeResult, None]:
        """Execute the LLM node, yielding streaming text results.

        Yields NodeResult objects as the LLM streams its response.
        """
        prompt = self._build_prompt(context_data or {})

        if self.llm_service:
            self.llm_service.add_user_message(prompt)
            full_reply = ""
            tool_calls = None

            async for chunk in self.llm_service.stream(
                tools=self._get_tools(context_data),
            ):
                if chunk["type"] == "sentence":
                    yield NodeResult(
                        text=chunk["content"],
                        is_final=bool(chunk.get("is_final", True)),
                    )
                    full_reply += chunk["content"]
                elif chunk["type"] == "finished":
                    full_reply = chunk.get("full_reply", full_reply)
                    tool_calls = chunk.get("tool_calls")

            if full_reply:
                self.llm_service.add_assistant_message(full_reply, tool_calls=tool_calls)

    def _build_prompt(self, context_data: dict) -> str:
        """Build the full prompt for this node."""
        parts = []
        if self.agent_information:
            parts.append(self.agent_information)
        if self.node.prompt:
            parts.append(self.node.prompt)
        if self.node.examples:
            lang = context_data.get("language", "en")
            example = self.node.examples.get(lang) or self.node.examples.get("en")
            if example:
                parts.append(f"\nExample response ({lang}): {example}")
        if self.node.rag_config:
            rag_context = self._get_rag_context(self.node.rag_config, context_data)
            if rag_context:
                parts.append(f"\nRelevant context:\n{rag_context}")
        context_str = "\n".join(f"{k}: {v}" for k, v in context_data.items() if k not in ("language",))
        if context_str:
            parts.append(f"\nContext:\n{context_str}")
        return "\n\n".join(parts)

    def _get_rag_context(self, rag_config: GraphNodeRAGConfig, context_data: dict) -> str:
        """Retrieve RAG context if service is available."""
        if not self.rag_service:
            return ""
        try:
            query = context_data.get("last_user_input", "")
            if not query:
                return ""
            results = self.rag_service.query(
                query=query,
                top_k=rag_config.similarity_top_k,
                score_threshold=rag_config.score_threshold,
            )
            return results
        except Exception as exc:
            logger.warning("[LLMNode] RAG query failed: %s", exc)
            return ""

    def _get_tools(self, context_data: dict) -> list | None:
        """Get tool configurations for this node."""
        if self.node.function_call:
            return "auto" if self.node.function_call == "auto" else [{"name": self.node.function_call}]
        return None


class StaticNode:
    """A node that plays a pre-cached audio message.

    Zero LLM cost — the message is pre-defined and cached.
    Typical latency: ~50ms.
    """

    def __init__(self, node: GraphNode):
        self.node = node

    async def execute(
        self,
        context_data: dict | None = None,
    ) -> AsyncGenerator[NodeResult, None]:
        """Play the static message with minimal latency."""
        message = self.node.static_message or ""
        if self.node.examples:
            lang = (context_data or {}).get("language", "en")
            message = self.node.examples.get(lang) or self.node.examples.get("en") or message

        yield NodeResult(text=message, is_final=True, audio_data=None)


class ToolNode:
    """A node that executes a function/tool call.

    Used for call transfer, API integration, database lookups, etc.
    """

    def __init__(self, node: GraphNode, tool_executor=None):
        self.node = node
        self.tool_executor = tool_executor

    async def execute(
        self,
        context_data: dict | None = None,
        user_input: str | None = None,
    ) -> AsyncGenerator[NodeResult, None]:
        """Execute the configured tool."""
        if not self.tool_executor:
            yield NodeResult(
                text="I'm sorry, I'm unable to process that request right now.",
                is_final=True,
            )
            return

        try:
            result = await self.tool_executor(
                tool_name=self.node.function_call or "",
                args=context_data or {},
                user_input=user_input or "",
            )
            yield NodeResult(
                text=result.get("message", ""),
                is_final=True,
                tool_calls=[result],
                target_node_id=result.get("target_node_id"),
            )
        except Exception as exc:
            logger.error("[ToolNode] Tool execution failed: %s", exc)
            yield NodeResult(
                text="I apologize, but I encountered an error processing your request.",
                is_final=True,
            )
