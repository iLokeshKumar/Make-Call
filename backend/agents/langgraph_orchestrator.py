"""
Rio CRM — Pre/Post Call Orchestration Shim  (agents/langgraph_orchestrator.py)
===============================================================================

This module is ACTIVE and serves two purposes:

1. Compatibility shim
   Exposes the original public entry points that external code may import:
     run_researcher(lead_id, company_id, actor_user_id) → dict
     run_post_call_workflow(lead_id, company_id, ...)    → dict
   Both delegate to the optimised specialist graphs first, then fall back
   to the inline node implementations here if those graphs fail.

2. Fallback node implementations
   Contains standalone Python functions (no LLM dependency) for the full
   post-call workflow:
     researcher_agent   — enrich + score lead
     voice_agent        — routing decision (book_demo / send_followup / none)
     summarizer_agent   — save call summary to CRM
     book_demo_agent    — update lead status + send demo confirmation email
     nurture_agent      — update lead status for non-demo outcomes
   These run synchronously and are used when LangGraph/LLM is unavailable.

Relationship to other orchestration files
-----------------------------------------
  agents/graph.py              — live voice-call chatbot (ReAct + tools)
  agents/pre_call_graph.py     — optimised pre-call LangGraph workflow
  agents/post_call_graph.py    — optimised post-call LangGraph workflow
  agents/orchestrator.py       — master multi-agent supervisor (9 agents)

Do NOT delete this file — it is the guaranteed-available fallback layer.
"""
import logging
from typing import TypedDict, List, Optional
from datetime import datetime

try:
    from langgraph.graph import StateGraph, END
    _LANGGRAPH_AVAILABLE = True
except ImportError:  # pragma: no cover
    StateGraph = None  # type: ignore[assignment,misc]
    END = "__end__"  # type: ignore[assignment]
    _LANGGRAPH_AVAILABLE = False

from database import engine
from sqlmodel import Session, select

logger = logging.getLogger(__name__)


# Shared state

class AgentState(TypedDict):
    """Shared state passed between all LangGraph nodes."""
    lead_id: int
    company_id: int
    actor_user_id: int
    lead_name: str
    lead_email: str
    lead_phone: str
    call_transcript: Optional[str]
    call_duration: int
    icp_score: float
    bant_answers: dict
    next_action: str        # "book_demo" | "send_followup" | "none"
    appointment_id: Optional[int]
    follow_up_sent: bool
    call_outcome: Optional[str]
    sentiment: Optional[str]
    pain_points: List[str]
    questions_asked: List[str]
    timestamp: str


# RESEARCHER AGENT — pre-call enrichment & scoring

def researcher_agent(state: AgentState) -> AgentState:
    """
    Enriches the lead and refreshes the ICP score before the call starts.
    Uses enrich_lead_if_needed + score_lead from demand_generation_service.
    """
    logger.info("[RESEARCHER] Enriching lead %s for company %s", state["lead_id"], state["company_id"])
    try:
        from services.leads.demand_generation_service import enrich_lead_if_needed, score_lead
        with Session(engine) as session:
            enrich_lead_if_needed(
                session=session,
                company_id=state["company_id"],
                actor_user_id=state["actor_user_id"],
                lead_id=state["lead_id"],
            )
            result = score_lead(
                session=session,
                company_id=state["company_id"],
                lead_id=state["lead_id"],
            )
            state["icp_score"] = float(result.get("score") or 0.5)
            logger.info("[RESEARCHER] Lead %s enriched, ICP=%.2f", state["lead_id"], state["icp_score"])
    except Exception as exc:
        logger.warning("[RESEARCHER] Enrichment failed: %s", exc)

    state["bant_answers"] = {"budget": None, "authority": None, "need": None, "timeline": None}
    state["pain_points"] = []
    state["questions_asked"] = []
    state["timestamp"] = datetime.now().isoformat()
    return state


# VOICE AGENT — pass-through

def voice_agent(state: AgentState) -> AgentState:
    """
    Pass-through node. Real voice call data is injected into state by
    run_post_call_workflow() before the graph executes.
    """
    logger.info("[VOICE AGENT] Transcript length=%s, outcome=%s",
                len(state.get("call_transcript") or ""), state.get("call_outcome"))
    # Route to appropriate post-call action
    if (state.get("icp_score", 0) > 0.75 and state.get("call_outcome") == "positive"):
        state["next_action"] = "book_demo"
    elif state.get("call_outcome") == "not_qualified":
        state["next_action"] = "none"
    else:
        state["next_action"] = "send_followup"
    return state


# SUMMARIZER AGENT — save call summary to CRM

def summarizer_agent(state: AgentState) -> AgentState:
    """Saves a structured call summary as a CRM interaction record."""
    logger.info("[SUMMARIZER] Saving call summary for lead %s", state["lead_id"])
    try:
        from agents.post_call_nurture import CallSummarizer
        summary = CallSummarizer.summarize_call(
            lead_id=state["lead_id"],
            transcript=state.get("call_transcript") or "",
            icp_score=state.get("icp_score", 0.5),
            sentiment=state.get("sentiment") or "neutral",
            pain_points=state.get("pain_points", []),
            questions_asked=state.get("questions_asked", []),
            bant_answers=state.get("bant_answers", {}),
        )
        CallSummarizer.save_summary_to_crm(
            lead_id=state["lead_id"],
            summary=summary,
            company_id=state["company_id"],
            actor_user_id=state["actor_user_id"],
        )
    except Exception as exc:
        logger.warning("[SUMMARIZER] Failed: %s", exc)
    return state


# DECISION — conditional edge

def determine_next_action(state: AgentState) -> str:
    action = state.get("next_action", "none")
    if action == "book_demo":
        return "book_demo_agent"
    if action == "send_followup":
        return "nurture_agent"
    return END


# BOOK DEMO AGENT — update lead status + send confirmation email

def book_demo_agent(state: AgentState) -> AgentState:
    """Updates lead to Demo Scheduled and sends a confirmation email."""
    logger.info("[BOOKING] Processing demo booking for lead %s", state["lead_id"])
    try:
        from agents.post_call_nurture import CRMUpdater, EmailWriter
        with Session(engine) as session:
            CRMUpdater.update_lead_status(
                lead_id=state["lead_id"],
                new_status="Demo Scheduled",
                notes="Demo booked automatically by post-call workflow.",
            )
            if state.get("lead_email"):
                EmailWriter.send_personalized_followup(
                    session=session,
                    company_id=state["company_id"],
                    actor_user_id=state["actor_user_id"],
                    lead_id=state["lead_id"],
                    lead_name=state.get("lead_name", "there"),
                    lead_email=state["lead_email"],
                    company="",
                    pain_points=state.get("pain_points", []),
                    questions=state.get("questions_asked", []),
                    icp_score=state.get("icp_score", 0.85),
                    suggested_action="book_demo",
                )
                state["follow_up_sent"] = True
    except Exception as exc:
        logger.warning("[BOOKING] Failed: %s", exc)
    return state


# NURTURE AGENT — personalized follow-up email for non-demo leads

def nurture_agent(state: AgentState) -> AgentState:
    """
    Updates CRM lead status for non-demo leads.
    Email is sent directly by post_call_service.py (EmailWriter block) to avoid duplicates.
    """
    logger.info("[NURTURE] Updating CRM status for lead %s", state["lead_id"])
    try:
        from agents.post_call_nurture import CRMUpdater
        new_status = "Not Qualified" if state.get("call_outcome") == "not_qualified" else "Follow-up"
        CRMUpdater.update_lead_status(
            lead_id=state["lead_id"],
            new_status=new_status,
            notes=f"Post-call nurture. Outcome: {state.get('call_outcome')}",
        )
        state["follow_up_sent"] = True
    except Exception as exc:
        logger.warning("[NURTURE] CRM update failed: %s", exc)
    return state


# GRAPH — compiled once at module level (not rebuilt per call)

def _build_post_call_graph():
    """
    Post-call graph: voice (pass-through) → summarizer → decision → booking|nurture.
    """
    if not _LANGGRAPH_AVAILABLE:
        return None
    workflow = StateGraph(AgentState)
    workflow.add_node("voice", voice_agent)
    workflow.add_node("summarizer", summarizer_agent)
    workflow.add_node("book_demo_agent", book_demo_agent)
    workflow.add_node("nurture_agent", nurture_agent)
    workflow.set_entry_point("voice")
    workflow.add_edge("voice", "summarizer")
    workflow.add_conditional_edges(
        "summarizer",
        determine_next_action,
        {"book_demo_agent": "book_demo_agent", "nurture_agent": "nurture_agent", END: END},
    )
    workflow.add_edge("book_demo_agent", END)
    workflow.add_edge("nurture_agent", END)
    return workflow.compile()

# Compiled once — reused across all invocations
_post_call_app = _build_post_call_graph()


# PUBLIC ENTRY POINTS

async def run_researcher(lead_id: int, company_id: int, actor_user_id: int) -> dict:
    """
    Pre-call entry point — delegates to pre_call_graph.run_pre_call_workflow().
    Kept for backward compatibility with dialer_service.py.
    """
    try:
        from agents.pre_call_graph import run_pre_call_workflow
        return await run_pre_call_workflow(lead_id, company_id, actor_user_id)
    except Exception as exc:
        logger.warning("[Orchestrator] pre_call_graph failed, running researcher_agent directly: %s", exc)
        state: AgentState = {
            "lead_id": lead_id, "company_id": company_id, "actor_user_id": actor_user_id,
            "lead_name": "", "lead_email": "", "lead_phone": "",
            "call_transcript": None, "call_duration": 0, "icp_score": 0.5,
            "bant_answers": {}, "next_action": "", "appointment_id": None,
            "follow_up_sent": False, "call_outcome": None, "sentiment": None,
            "pain_points": [], "questions_asked": [], "timestamp": "",
        }
        result = researcher_agent(state)
        return {"lead_id": lead_id, "icp_score": result["icp_score"]}


async def run_post_call_workflow(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
    lead_name: str,
    lead_email: str,
    call_transcript: str,
    call_duration: int,
    call_outcome: str,
    sentiment: str,
    icp_score: float,
    pain_points: List[str],
    questions_asked: List[str],
    bant_answers: dict,
) -> dict:
    """
    Post-call entry point — delegates to post_call_graph.run_post_call_workflow().
    Kept for backward compatibility with post_call_service.py.
    """
    try:
        from agents.post_call_graph import run_post_call_workflow as _run
        return await _run(
            lead_id=lead_id, company_id=company_id, actor_user_id=actor_user_id,
            lead_name=lead_name, lead_email=lead_email, call_transcript=call_transcript,
            call_duration=call_duration, call_outcome=call_outcome, sentiment=sentiment,
            icp_score=icp_score, pain_points=pain_points, questions_asked=questions_asked,
            bant_answers=bant_answers,
        )
    except Exception as exc:
        logger.warning("[Orchestrator] post_call_graph failed, running nodes directly: %s", exc)

    # Fallback: legacy node execution
    state: AgentState = {
        "lead_id": lead_id, "company_id": company_id, "actor_user_id": actor_user_id,
        "lead_name": lead_name, "lead_email": lead_email, "lead_phone": "",
        "call_transcript": call_transcript, "call_duration": call_duration,
        "icp_score": icp_score, "bant_answers": bant_answers, "next_action": "",
        "appointment_id": None, "follow_up_sent": False, "call_outcome": call_outcome,
        "sentiment": sentiment, "pain_points": pain_points, "questions_asked": questions_asked,
        "timestamp": datetime.now().isoformat(),
    }
    state = voice_agent(state)
    state = summarizer_agent(state)
    next_node = determine_next_action(state)
    if next_node == "book_demo_agent":
        state = book_demo_agent(state)
    elif next_node == "nurture_agent":
        state = nurture_agent(state)
    return {
        "lead_id": state["lead_id"],
        "next_action": state["next_action"],
        "follow_up_sent": state["follow_up_sent"],
    }
