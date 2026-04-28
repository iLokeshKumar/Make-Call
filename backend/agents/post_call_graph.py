"""
Post-call workflow: summarizer_node -> decision -> book_demo_node | nurture_node -> END

Called from post_call_service.py after a call transcript is ready.
Replaces the post-call section of langgraph_orchestrator.py.
"""
from __future__ import annotations
import logging
from typing import List
from sqlmodel import Session
from database import engine
from .state import RioState, empty_state
from .checkpointer import get_checkpointer
from utils.tracing import traceable, traceable_async
logger = logging.getLogger(__name__)

@traceable(name="summarizer_node", run_type="chain", tags=["post_call"])
def summarizer_node(state: RioState) -> RioState:
    """Classify outcome, extract insights, save call summary to CRM."""
    logger.info("[SummarizerNode] lead=%s", state.get("lead_id"))
    state["current_agent"] = "post_call"
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
        # Determine routing
        icp = state.get("icp_score", 0)
        outcome = state.get("call_outcome", "")
        if icp > 0.75 and outcome == "positive":
            state["next_agent"] = "book_demo"
        elif outcome == "not_qualified":
            state["next_agent"] = "nurture"
        else:
            state["next_agent"] = "nurture"
        state["agent_results"]["post_call"] = {"summary": summary, "next": state["next_agent"]}
    except Exception as exc:
        logger.warning("[SummarizerNode] Failed: %s", exc)
        state["errors"].append(f"summarizer_node: {exc}")
        state["next_agent"] = "nurture"
    return state

@traceable(name="book_demo_node", run_type="chain", tags=["post_call", "booking"])
def book_demo_node(state: RioState) -> RioState:
    """Update lead to Demo Scheduled and send confirmation email."""
    logger.info("[BookDemoNode] lead=%s", state.get("lead_id"))
    state["current_agent"] = "book_demo"
    try:
        from agents.post_call_nurture import CRMUpdater, EmailWriter
        CRMUpdater.update_lead_status(
            lead_id=state["lead_id"],
            new_status="Demo Scheduled",
            notes="Demo booked automatically by post-call workflow.",
        )
        lead_email = state.get("lead_data", {}).get("email") or ""
        if lead_email:
            with Session(engine) as session:
                EmailWriter.send_personalized_followup(
                    session=session,
                    company_id=state["company_id"],
                    actor_user_id=state["actor_user_id"],
                    lead_id=state["lead_id"],
                    lead_name=state.get("lead_data", {}).get("name", ""),
                    lead_email=lead_email,
                    company=state.get("lead_data", {}).get("company_name", ""),
                    pain_points=state.get("pain_points", []),
                    questions=state.get("questions_asked", []),
                    icp_score=state.get("icp_score", 0.85),
                    suggested_action="book_demo",
                )
        state["agent_results"]["book_demo"] = {"email_sent": bool(lead_email)}
    except Exception as exc:
        logger.warning("[BookDemoNode] Failed: %s", exc)
        state["errors"].append(f"book_demo_node: {exc}")
    state["next_agent"] = ""
    return state

@traceable(name="nurture_node", run_type="chain", tags=["post_call", "nurture"])
def nurture_node(state: RioState) -> RioState:
    """Update lead CRM status for non-demo leads."""
    logger.info("[NurtureNode] lead=%s outcome=%s", state.get("lead_id"), state.get("call_outcome"))
    state["current_agent"] = "nurture"
    try:
        from agents.post_call_nurture import CRMUpdater
        new_status = "Not Qualified" if state.get("call_outcome") == "not_qualified" else "Follow-up"
        CRMUpdater.update_lead_status(
            lead_id=state["lead_id"],
            new_status=new_status,
            notes=f"Post-call nurture. Outcome: {state.get('call_outcome')}",
        )
        state["agent_results"]["nurture"] = {"new_status": new_status}
    except Exception as exc:
        logger.warning("[NurtureNode] CRM update failed: %s", exc)
        state["errors"].append(f"nurture_node: {exc}")
    state["next_agent"] = ""
    return state

def _route_after_summary(state: RioState) -> str:
    from langgraph.graph import END
    nxt = state.get("next_agent", "nurture")
    if nxt == "book_demo":
        return "book_demo"
    return "nurture"

try:
    from langgraph.graph import StateGraph, END
    _wf = StateGraph(RioState)
    _wf.add_node("summarizer", summarizer_node)
    _wf.add_node("book_demo", book_demo_node)
    _wf.add_node("nurture", nurture_node)
    _wf.set_entry_point("summarizer")
    _wf.add_conditional_edges("summarizer", _route_after_summary,
                              {"book_demo": "book_demo", "nurture": "nurture"})
    _wf.add_edge("book_demo", END)
    _wf.add_edge("nurture", END)
    post_call_app = _wf.compile(checkpointer=get_checkpointer())
    _POST_CALL_AVAILABLE = True
except Exception as _e:
    post_call_app = None
    _POST_CALL_AVAILABLE = False

@traceable_async(name="run_post_call_workflow", run_type="chain", tags=["post_call"])
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
    Entry point called by post_call_service after a call ends.
    Preserves the same signature as langgraph_orchestrator.run_post_call_workflow.
    """
    state = empty_state(company_id=company_id, actor_user_id=actor_user_id, lead_id=lead_id)
    state.update({
        "lead_data": {"name": lead_name, "email": lead_email},
        "call_transcript": call_transcript,
        "call_duration": call_duration,
        "call_outcome": call_outcome,
        "sentiment": sentiment,
        "icp_score": icp_score,
        "pain_points": pain_points,
        "questions_asked": questions_asked,
        "bant_answers": bant_answers,
    })
    if post_call_app:
        try:
            config = {"configurable": {"thread_id": f"post_call_{company_id}_{lead_id}"}}
            final = await post_call_app.ainvoke(state, config=config)
            return {
                "lead_id": lead_id,
                "next_action": final.get("agent_results", {}).get("post_call", {}).get("next", ""),
                "follow_up_sent": "book_demo" in final.get("agent_results", {}),
                "errors": final.get("errors", []),
            }
        except Exception as exc:
            import logging as _lg
            _lg.getLogger(__name__).warning("[PostCallGraph] Graph failed: %s", exc)
    # Fallback: run nodes sequentially
    state = summarizer_node(state)
    nxt = _route_after_summary(state)
    if nxt == "book_demo":
        state = book_demo_node(state)
    else:
        state = nurture_node(state)
    return {
        "lead_id": lead_id,
        "next_action": state.get("agent_results", {}).get("post_call", {}).get("next", ""),
        "follow_up_sent": "book_demo" in state.get("agent_results", {}),
        "errors": state.get("errors", []),
    }
