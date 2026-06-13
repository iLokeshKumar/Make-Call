from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class EdgeConditionType(str, Enum):
    """Type of routing condition on a graph edge."""

    LLM = "llm"
    EXPRESSION = "expression"
    EVENT = "event"
    UNCONDITIONAL = "unconditional"


class HangupReason(str, Enum):
    """Reasons a graph agent might terminate a call."""

    LLM_PROMPTED_HANGUP = "llm_prompted_hangup"
    VOICEMAIL_DETECTED = "voicemail_detected"
    MAX_DURATION_REACHED = "max_duration_reached"
    INACTIVITY_TIMEOUT = "inactivity_timeout"
    END_CALL_TOOL = "end_call_tool"
    COMPLETION_DETECTED = "completion_detected"
    TRANSFERRED = "transferred"
    ERROR = "error"


class GraphNodeRAGConfig(BaseModel):
    """Per-node RAG configuration."""

    vector_store: str = "chromadb"
    similarity_top_k: int = 5
    score_threshold: float = 0.1
    model: Optional[str] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None


class GraphEdge(BaseModel):
    """An edge connecting two nodes in the conversation graph.

    Each edge has a condition that determines whether the transition
    is taken. Edges are evaluated in priority order (lower = first).
    """

    to_node_id: str
    condition: Optional[str] = None
    condition_type: EdgeConditionType = EdgeConditionType.LLM
    priority: int = 100

    def model_dump(self, **kwargs) -> dict:
        return super().model_dump(**kwargs)


class GraphNode(BaseModel):
    """A single node in the conversation graph.

    Each node has one clear purpose: greet, qualify, collect info,
    confirm, transfer, etc.
    """

    id: str
    prompt: Optional[str] = None
    node_type: str = "llm"
    static_message: Optional[str] = None
    edges: list[GraphEdge] = Field(default_factory=list)
    examples: Optional[dict[str, str]] = None
    repeat_after_silence_seconds: Optional[float] = None
    function_call: Optional[str] = None
    rag_config: Optional[GraphNodeRAGConfig] = None

    def model_dump(self, **kwargs) -> dict:
        return super().model_dump(**kwargs)


class GraphAgentConfig(BaseModel):
    """Top-level configuration for a graph-based voice agent."""

    agent_type: str = "graph_agent"
    agent_information: Optional[str] = None
    routing_instructions: Optional[str] = None
    current_node_id: str
    nodes: list[GraphNode]
    model: Optional[str] = None
    routing_model: Optional[str] = None
    routing_max_tokens: int = 250
    routing_reasoning_effort: Optional[str] = None
    context_data: dict[str, Any] = Field(default_factory=dict)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        for node in self.nodes:
            if node.id == node_id:
                return node
        return None


class RoutingLog(BaseModel):
    """Audit log entry for each routing decision."""

    from_node_id: str
    from_node_type: str
    to_node_id: str
    condition_type: str
    condition_evaluated: str
    result: bool
    routing_latency_ms: float
    edge_count: int
    matched_edge_index: int
