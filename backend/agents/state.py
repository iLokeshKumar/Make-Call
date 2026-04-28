"""
RioState — the single shared TypedDict that flows through every LangGraph node.

Design rules:
  - Researcher populates: lead_data, interaction_history, icp_score, kb_context
  - Voice pipeline injects: call_transcript, call_outcome, call_duration, sentiment
  - Post-call agents write: bant_answers, pain_points, objections_raised, questions_asked
  - Each agent appends its output to agent_results[agent_name]
  - Supervisor reads next_agent to decide routing; nodes set it to "" when done
  - errors is append-only — nodes append on failure, never overwrite
"""
from __future__ import annotations

from typing import Annotated, List, Optional

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class RioState(TypedDict):
    # LangGraph message history (accumulates with add_messages reducer)
    messages: Annotated[List[BaseMessage], add_messages]

    # Supervisor routing
    next_agent: str # supervisor writes the next node name; "" = done
    current_agent: str # which node is currently executing

    lead_id: Optional[int]
    company_id: int
    actor_user_id: int

    lead_data: dict
    interaction_history: list

    # Call context — injected by voice pipeline / post_call_service
    call_transcript: Optional[str]
    call_outcome: Optional[str] # "positive" | "neutral" | "not_qualified"
    call_duration: int # seconds
    sentiment: Optional[str] # "positive" | "neutral" | "negative"

    # Qualification data
    icp_score: float
    bant_answers: dict # {budget, authority, need, timeline}
    pain_points: List[str]
    objections_raised: List[str]
    questions_asked: List[str]

    # RAG context — populated by knowledge_node, read by voice/coach/researcher
    kb_context: List[str] # formatted text chunks ready for LLM injection

    # Per-agent outputs
    agent_results: dict # {"researcher": {...}, "coach": {...}, ...}

    # Error log — append-only
    errors: List[str]


def empty_state(
    company_id: int,
    actor_user_id: int,
    lead_id: Optional[int] = None,
) -> RioState:
    """Return a fully initialised RioState with safe defaults."""
    return RioState(
        messages=[],
        next_agent="",
        current_agent="",
        lead_id=lead_id,
        company_id=company_id,
        actor_user_id=actor_user_id,
        lead_data={},
        interaction_history=[],
        call_transcript=None,
        call_outcome=None,
        call_duration=0,
        sentiment=None,
        icp_score=0.5,
        bant_answers={"budget": None, "authority": None, "need": None, "timeline": None},
        pain_points=[],
        objections_raised=[],
        questions_asked=[],
        kb_context=[],
        agent_results={},
        errors=[],
    )
