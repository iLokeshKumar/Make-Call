"""Edge condition evaluation for graph agents.

Supports four condition types:
- LLM: Uses a cheaper/faster LLM to decide the transition
- Expression: Deterministic side-effect-free expression evaluation
- Event: External event-driven transitions (via REST/WebSocket)
- Unconditional: Always follows the defined path
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from .models import EdgeConditionType, GraphEdge, GraphNode

logger = logging.getLogger(__name__)

_OPERATORS = {
    "eq": lambda a, b: a == b,
    "neq": lambda a, b: a != b,
    "gt": lambda a, b: _to_number(a) > _to_number(b) if _is_numeric(a) and _is_numeric(b) else str(a) > str(b),
    "gte": lambda a, b: _to_number(a) >= _to_number(b) if _is_numeric(a) and _is_numeric(b) else str(a) >= str(b),
    "lt": lambda a, b: _to_number(a) < _to_number(b) if _is_numeric(a) and _is_numeric(b) else str(a) < str(b),
    "lte": lambda a, b: _to_number(a) <= _to_number(b) if _is_numeric(a) and _is_numeric(b) else str(a) <= str(b),
    "in": lambda a, b: a in (b if isinstance(b, (list, tuple, set)) else [b]),
    "not_in": lambda a, b: a not in (b if isinstance(b, (list, tuple, set)) else [b]),
    "contains": lambda a, b: b in a if isinstance(a, (str, list, tuple)) else False,
    "exists": lambda a, b: a is not None,
    "not_exists": lambda a, b: a is None,
}


def _is_numeric(v: Any) -> bool:
    return isinstance(v, (int, float))


def _to_number(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _resolve_variable(path: str, context: dict) -> Any:
    """Resolve a dot-notation path against context data.

    Example: "detected_language" -> context["detected_language"]
             "recipient_data.timezone" -> context["recipient_data"]["timezone"]
    """
    parts = path.split(".")
    current = context
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


class ExpressionEvaluator:
    """Side-effect-free, no-eval expression evaluator for deterministic routing.

    Expression syntax:
        {"and": [
            {"eq": ["detected_language", "hi"]},
            {"gte": ["retry_count", 3]}
        ]}
        {"or": [
            {"eq": ["caller_intent", "complaint"]},
            {"contains": ["transcript", "escalate"]}
        ]}
        {"eq": ["current_node_id", "greeting"]}
    """

    @classmethod
    def evaluate(cls, expression: Any, context: dict) -> bool:
        if not isinstance(expression, dict):
            return False

        if "and" in expression:
            conditions = expression["and"]
            return all(cls.evaluate(c, context) for c in conditions)

        if "or" in expression:
            conditions = expression["or"]
            return any(cls.evaluate(c, context) for c in conditions)

        if "not" in expression:
            return not cls.evaluate(expression["not"], context)

        for op_name, operands in expression.items():
            if op_name in _OPERATORS:
                if not isinstance(operands, (list, tuple)) or len(operands) < 2:
                    logger.warning("[ExprEval] Invalid operands for %s: %r", op_name, operands)
                    return False
                a = _resolve_variable(str(operands[0]), context) if isinstance(operands[0], str) else operands[0]
                b = _resolve_variable(str(operands[1]), context) if isinstance(operands[1], str) else operands[1]
                result = _OPERATORS[op_name](a, b)
                return result

        logger.warning("[ExprEval] Unknown expression: %r", expression)
        return False


class EdgeEvaluator:
    """Evaluates edges on a node and returns the matched edge."""

    def __init__(
        self,
        routing_llm_callable=None,
        context_data: dict | None = None,
    ):
        self._routing_llm = routing_llm_callable
        self.context_data = context_data or {}

    async def evaluate(
        self,
        node: GraphNode,
        transcript: str,
        event_payload: dict | None = None,
    ) -> tuple[Optional[GraphEdge], Optional[dict]]:
        """Evaluate all edges on a node, return (matched_edge, metadata).

        Evaluation order:
        1. Unconditional edges (priority < 0 or condition_type=unconditional)
        2. Expression edges (condition_type=expression)
        3. Event edges (condition_type=event)
        4. LLM edges (condition_type=llm) — most expensive, evaluated last

        Within each type, edges are evaluated in priority order (lower first).
        """
        edges = sorted(node.edges, key=lambda e: e.priority)

        metadata = {
            "from_node_id": node.id,
            "from_node_type": node.node_type,
            "evaluated_edges": [],
            "matched_edge_index": -1,
        }

        # Phase 1: Unconditional edges
        for idx, edge in enumerate(edges):
            if edge.condition_type == EdgeConditionType.UNCONDITIONAL:
                metadata["evaluated_edges"].append({
                    "to": edge.to_node_id,
                    "type": "unconditional",
                    "matched": True,
                })
                metadata["matched_edge_index"] = idx
                logger.info("[GraphAgent] Unconditional edge → %s", edge.to_node_id)
                return edge, metadata

        # Phase 2: Expression edges (deterministic, zero LLM cost)
        for idx, edge in enumerate(edges):
            if edge.condition_type == EdgeConditionType.EXPRESSION and edge.condition:
                try:
                    start = time.time()
                    result = ExpressionEvaluator.evaluate(
                        self._parse_expression(edge.condition),
                        self.context_data,
                    )
                    latency = (time.time() - start) * 1000
                    metadata["evaluated_edges"].append({
                        "to": edge.to_node_id,
                        "type": "expression",
                        "condition": edge.condition,
                        "matched": result,
                        "latency_ms": round(latency, 2),
                    })
                    if result:
                        metadata["matched_edge_index"] = idx
                        logger.info("[GraphAgent] Expression match → %s (cond=%r)", edge.to_node_id, edge.condition)
                        return edge, metadata
                except Exception as exc:
                    logger.warning("[GraphAgent] Expression eval error: %s", exc)

        # Phase 3: Event edges
        if event_payload:
            for idx, edge in enumerate(edges):
                if edge.condition_type == EdgeConditionType.EVENT:
                    matched = self._evaluate_event(edge, event_payload)
                    metadata["evaluated_edges"].append({
                        "to": edge.to_node_id,
                        "type": "event",
                        "matched": matched,
                    })
                    if matched:
                        metadata["matched_edge_index"] = idx
                        logger.info("[GraphAgent] Event match → %s", edge.to_node_id)
                        return edge, metadata

        # Phase 4: LLM edges (most expensive — use cheaper routing model)
        llm_edges = [e for e in edges if e.condition_type == EdgeConditionType.LLM]
        if llm_edges and self._routing_llm:
            try:
                start = time.time()
                chosen_edge = await self._evaluate_llm_edges(node, llm_edges, transcript)
                latency = (time.time() - start) * 1000
                if chosen_edge:
                    for idx, edge in enumerate(edges):
                        if edge.to_node_id == chosen_edge.to_node_id:
                            metadata["evaluated_edges"].append({
                                "to": edge.to_node_id,
                                "type": "llm",
                                "matched": True,
                                "latency_ms": round(latency, 2),
                            })
                            metadata["matched_edge_index"] = idx
                            logger.info("[GraphAgent] LLM routing → %s", chosen_edge.to_node_id)
                            return chosen_edge, metadata

                metadata["evaluated_edges"].append({
                    "type": "llm",
                    "matched": False,
                    "latency_ms": round(latency, 2),
                    "note": "no edge matched or LLM returned stay",
                })
            except Exception as exc:
                logger.warning("[GraphAgent] LLM routing error: %s", exc)

        # No edge matched — stay on current node
        metadata["matched_edge_index"] = -1
        logger.info("[GraphAgent] No edge matched — staying on node %s", node.id)
        return None, metadata

    def _parse_expression(self, condition: str) -> Any:
        """Parse expression from string or dict.

        Accepts JSON string or already-parsed dict.
        """
        import json
        if isinstance(condition, str):
            try:
                return json.loads(condition)
            except json.JSONDecodeError:
                return {"eq": [condition.strip(), True]}
        return condition

    def _evaluate_event(self, edge: GraphEdge, event_payload: dict) -> bool:
        """Evaluate whether an event matches this event edge condition."""
        if not edge.condition or not event_payload:
            return False
        condition = self._parse_expression(edge.condition)
        if isinstance(condition, dict) and "event_type" in condition:
            return event_payload.get("event_type") == condition["event_type"]
        return ExpressionEvaluator.evaluate(condition, {**self.context_data, "event": event_payload})

    async def _evaluate_llm_edges(
        self,
        node: GraphNode,
        llm_edges: list[GraphEdge],
        transcript: str,
    ) -> Optional[GraphEdge]:
        """Use the routing LLM to decide which LLM-typed edge to follow."""
        routing_prompt = self._build_routing_prompt(node, llm_edges, transcript)
        result = await self._routing_llm(routing_prompt)
        for edge in llm_edges:
            if edge.to_node_id in result or result.strip().lower() == edge.to_node_id.lower():
                return edge
        if result.strip().lower() in ("stay", "none", "current"):
            return None
        for edge in llm_edges:
            if edge.condition and edge.condition.lower() in result.lower():
                return edge
        return None

    def _build_routing_prompt(self, node: GraphNode, llm_edges: list[GraphEdge], transcript: str) -> str:
        edges_desc = "\n".join(
            f"  {i+1}. Transition to '{e.to_node_id}' — {e.condition or 'default'}"
            for i, e in enumerate(llm_edges)
        )
        return (
            f"You are a conversation router for a voice agent.\n"
            f"Current node: '{node.id}'\n"
            f"Available transitions:\n{edges_desc}\n\n"
            f"Based on the conversation so far, which transition should be taken?\n"
            f"Reply with exactly the target node ID, or 'stay' to remain on the current node.\n\n"
            f"Conversation:\n{transcript}\n\n"
            f"Target node ID:"
        )
