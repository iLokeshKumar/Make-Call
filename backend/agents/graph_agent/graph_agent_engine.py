"""Core graph agent engine — orchestrates node traversal and routing.

The engine manages the conversation lifecycle through a series of nodes,
evaluating edges after each user input to determine the next node.
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Callable, Optional

from .models import (
    EdgeConditionType,
    GraphAgentConfig,
    GraphNode,
    HangupReason,
    RoutingLog,
)
from .edge_evaluator import EdgeEvaluator
from .node_types import LLMNode, NodeResult, StaticNode, ToolNode

logger = logging.getLogger(__name__)


class GraphAgentEngine:
    """Orchestrates a conversation through a graph of nodes.

    Usage:
        engine = GraphAgentEngine(config, llm_service=llm, rag_service=rag)
        async for result in engine.process_turn(user_input, transcript):
            # result.text -> TTS output
            # result.hangup -> end call
    """

    def __init__(
        self,
        config: GraphAgentConfig,
        llm_service=None,
        rag_service=None,
        tool_executor: Callable | None = None,
        routing_llm_callable: Callable | None = None,
    ):
        self.config = config
        self.current_node_id = config.current_node_id
        self.context_data = dict(config.context_data or {})
        self.llm_service = llm_service
        self.rag_service = rag_service
        self.tool_executor = tool_executor
        self.routing_llm_callable = routing_llm_callable
        self.edge_evaluator = EdgeEvaluator(
            routing_llm_callable=routing_llm_callable,
            context_data=self.context_data,
        )
        self.routing_log: list[RoutingLog] = []
        self._current_node_cache: Optional[GraphNode] = None

    @property
    def current_node(self) -> Optional[GraphNode]:
        if self._current_node_cache and self._current_node_cache.id == self.current_node_id:
            return self._current_node_cache
        self._current_node_cache = self.config.get_node(self.current_node_id)
        return self._current_node_cache

    @property
    def is_graph_agent(self) -> bool:
        return self.config.agent_type == "graph_agent"

    def get_current_node_context(self) -> dict:
        """Returns the current node's configuration for the VoicePipeline.

        This is used to determine which prompt/tools/static message to use.
        """
        node = self.current_node
        if not node:
            return {}

        context = {
            "node_id": node.id,
            "node_type": node.node_type,
            "prompt": self._build_node_prompt(node),
            "function_call": node.function_call,
            "rag_config": node.rag_config,
            "repeat_after_silence_seconds": node.repeat_after_silence_seconds,
        }

        if node.node_type == "static" and node.static_message:
            context["static_message"] = node.static_message

        return context

    async def process_turn(
        self,
        user_input: str,
        transcript: str,
        event_payload: dict | None = None,
    ) -> AsyncGenerator[NodeResult, None]:
        """Process a single user turn through the graph.

        Steps:
        1. Execute current node to generate response
        2. Evaluate edges to determine next node
        3. Repeat until we reach a terminal state or non-transitioning node
        """
        node = self.current_node
        if not node:
            logger.error("[GraphAgent] Current node %s not found in config", self.current_node_id)
            yield NodeResult(text="I'm sorry, I'm having trouble with my configuration.", is_final=True, hangup=True)
            return

        # Execute the current node
        executor = self._create_node_executor(node)
        node_text = ""

        async for result in executor.execute(
            transcript=transcript,
            context_data={**self.context_data, "last_user_input": user_input},
        ):
            node_text += result.text or ""

            if result.hangup:
                yield result
                return

            if result.tool_calls:
                self.context_data["last_tool_result"] = result.tool_calls

            # If a tool execution redirected us, follow it
            if result.target_node_id:
                next_node = self.config.get_node(result.target_node_id)
                if next_node:
                    self.current_node_id = result.target_node_id
                    self._current_node_cache = next_node
                    node = next_node
                    executor = self._create_node_executor(node)
                    continue

            yield result

        # If the node has no edges, or we should stay, we're done
        if not node.edges:
            return

        # Add node output to transcript context for routing
        routing_transcript = f"{transcript}\nAgent: {node_text}" if node_text else transcript

        # Evaluate edges to find next node
        matched_edge, metadata = await self.edge_evaluator.evaluate(
            node=node,
            transcript=routing_transcript,
            event_payload=event_payload,
        )

        # Log the routing decision
        log_entry = RoutingLog(
            from_node_id=node.id,
            from_node_type=node.node_type,
            to_node_id=matched_edge.to_node_id if matched_edge else node.id,
            condition_type=matched_edge.condition_type.value if matched_edge else "stay",
            condition_evaluated=str(metadata.get("evaluated_edges", [])),
            result=matched_edge is not None,
            routing_latency_ms=metadata.get("evaluated_edges", [{}])[-1].get("latency_ms", 0) if metadata.get("evaluated_edges") else 0,
            edge_count=len(node.edges),
            matched_edge_index=metadata.get("matched_edge_index", -1),
        )
        self.routing_log.append(log_entry)

        # Transition to next node if matched
        if matched_edge:
            self.current_node_id = matched_edge.to_node_id
            self._current_node_cache = None
            logger.info(
                "[GraphAgent] Transition: %s → %s (%s)",
                node.id, matched_edge.to_node_id, matched_edge.condition_type.value,
            )

    async def handle_event(
        self,
        event_payload: dict,
    ) -> Optional[str]:
        """Handle an external event that may trigger a node transition.

        Returns the target node ID if a transition occurred, None otherwise.
        """
        node = self.current_node
        if not node:
            return None

        matched_edge, metadata = await self.edge_evaluator.evaluate(
            node=node,
            transcript="",
            event_payload=event_payload,
        )

        if matched_edge:
            self.current_node_id = matched_edge.to_node_id
            self._current_node_cache = None
            logger.info(
                "[GraphAgent] Event triggered transition: %s → %s",
                node.id, matched_edge.to_node_id,
            )
            return matched_edge.to_node_id

        return None

    def update_context(self, key: str, value: Any) -> None:
        """Update context data (e.g., after extraction or tool call)."""
        self.context_data[key] = value
        # Also update the edge evaluator's context
        self.edge_evaluator.context_data = self.context_data

    def reset_to_node(self, node_id: str) -> bool:
        """Force-reset to a specific node (for debugging or override)."""
        node = self.config.get_node(node_id)
        if node:
            self.current_node_id = node_id
            self._current_node_cache = node
            return True
        return False

    def _create_node_executor(self, node: GraphNode):
        """Factory to create the appropriate node executor."""
        if node.node_type == "static":
            return StaticNode(node)
        elif node.node_type == "tool" or (node.function_call and node.function_call != "auto"):
            return ToolNode(node, tool_executor=self.tool_executor)
        else:
            return LLMNode(
                node=node,
                agent_information=self.config.agent_information,
                llm_service=self.llm_service,
                rag_service=self.rag_service,
            )

    def _build_node_prompt(self, node: GraphNode) -> str:
        """Build the full prompt for a node, combining agent info + node prompt."""
        parts = []
        if self.config.agent_information:
            parts.append(self.config.agent_information)
        if node.prompt:
            parts.append(node.prompt)
        if self.config.routing_instructions and node.edges:
            edges_desc = ", ".join(
                f"'{e.to_node_id}': {e.condition or 'default'}"
                for e in node.edges if e.condition_type == EdgeConditionType.LLM
            )
            if edges_desc:
                parts.append(f"\nRouting options:\n{edges_desc}")
        return "\n\n".join(parts)
