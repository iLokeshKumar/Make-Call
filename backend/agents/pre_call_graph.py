"""
Pre-call workflow: knowledge_node -> researcher_node -> END

Called from dialer_service.py before placing an outbound call.
Populates: kb_context, lead_data, icp_score in RioState.
"""
from __future__ import annotations
import logging
from typing import Optional
from sqlmodel import Session, select
from database import engine
from models.models import Interaction, Lead
from .state import RioState, empty_state
from .checkpointer import get_checkpointer
from utils.tracing import traceable, traceable_async
logger = logging.getLogger(__name__)

def _lead_to_dict(lead: Lead) -> dict:
    return {
        "id": lead.id, "name": lead.name, "email": lead.email,
        "normalized_phone": lead.normalized_phone, "status": lead.status,
        "ism_stage": lead.ism_stage, "source": lead.source,
        "company_name": lead.company_name, "job_title": lead.job_title,
        "enrichment_status": lead.enrichment_status, "lead_score": float(lead.lead_score or 0),
        "notes": lead.notes,
    }

@traceable(name="knowledge_node", run_type="chain", tags=["pre_call", "rag"])
def knowledge_node(state: RioState) -> RioState:
    """Search KB for context relevant to this lead before the call."""
    logger.info("[KnowledgeNode] lead=%s company=%s", state.get("lead_id"), state["company_id"])
    state["current_agent"] = "knowledge"
    try:
        from services.rag.query_engine import format_for_prompt, search
        lead_data = state.get("lead_data", {})
        query_parts = []
        if lead_data.get("company_name"):
            query_parts.append(lead_data["company_name"])
        if lead_data.get("notes"):
            query_parts.append(lead_data["notes"][:200])
        query = " ".join(query_parts) or "sales product information"
        product_ctx = search(query, state["company_id"], collection="products", n_results=3)
        obj_ctx = search(query, state["company_id"], collection="objections", n_results=2)
        comp_ctx = search(query, state["company_id"], collection="competitors", n_results=2)
        all_results = product_ctx + obj_ctx + comp_ctx
        state["kb_context"] = [r["content"] for r in all_results]
        state["agent_results"]["knowledge"] = {
            "chunks_retrieved": len(all_results),
            "collections_searched": ["products", "objections", "competitors"],
        }
        logger.info("[KnowledgeNode] Retrieved %d chunks", len(all_results))
    except Exception as exc:
        logger.warning("[KnowledgeNode] Failed: %s", exc)
        state["errors"].append(f"knowledge_node: {exc}")
    state["next_agent"] = ""
    return state

@traceable(name="researcher_node", run_type="chain", tags=["pre_call", "enrichment"])
def researcher_node(state: RioState) -> RioState:
    """Enrich the lead and compute ICP score."""
    logger.info("[ResearcherNode] lead=%s company=%s", state.get("lead_id"), state["company_id"])
    state["current_agent"] = "researcher"
    lead_id = state.get("lead_id")
    company_id = state["company_id"]
    try:
        with Session(engine) as session:
            lead = session.get(Lead, lead_id)
            if lead:
                state["lead_data"] = _lead_to_dict(lead)
            interactions = session.exec(
                select(Interaction)
                .where(Interaction.lead_id == lead_id)
                .order_by(Interaction.started_at.desc())
                .limit(10)
            ).all()
            state["interaction_history"] = [
                {"type": i.type, "channel": i.channel, "direction": i.direction,
                 "content": (i.content or "")[:300], "started_at": i.started_at.isoformat()}
                for i in interactions
            ]
            try:
                from services.leads.demand_generation_service import enrich_lead_if_needed, score_lead
                enrich_lead_if_needed(session=session, company_id=company_id,
                                      actor_user_id=state["actor_user_id"], lead_id=lead_id)
                result = score_lead(session=session, company_id=company_id, lead_id=lead_id)
                state["icp_score"] = float(result.get("score") or 0.5)
            except Exception as exc:
                logger.warning("[ResearcherNode] Enrichment/scoring failed: %s", exc)
            state["agent_results"]["researcher"] = {
                "icp_score": state["icp_score"],
                "interactions_fetched": len(interactions),
                "lead_enriched": True,
            }
    except Exception as exc:
        logger.warning("[ResearcherNode] Failed: %s", exc)
        state["errors"].append(f"researcher_node: {exc}")
    state["next_agent"] = ""
    return state

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.memory import MemorySaver
    _wf = StateGraph(RioState)
    _wf.add_node("knowledge", knowledge_node)
    _wf.add_node("researcher", researcher_node)
    _wf.set_entry_point("knowledge")
    _wf.add_edge("knowledge", "researcher")
    _wf.add_edge("researcher", END)
    pre_call_app = _wf.compile(checkpointer=get_checkpointer())
    logger.info = lambda *a, **k: None  # suppress at import time
    _PRE_CALL_AVAILABLE = True
except Exception as _e:
    pre_call_app = None
    _PRE_CALL_AVAILABLE = False

@traceable_async(name="run_pre_call_workflow", run_type="chain", tags=["pre_call"])
async def run_pre_call_workflow(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
) -> dict:
    """
    Entry point called by dialer_service before placing an outbound call.
    Returns the populated RioState as a dict (icp_score, kb_context, lead_data).
    """
    state = empty_state(company_id=company_id, actor_user_id=actor_user_id, lead_id=lead_id)
    if pre_call_app:
        try:
            config = {"configurable": {"thread_id": f"pre_call_{company_id}_{lead_id}"}}
            final = await pre_call_app.ainvoke(state, config=config)
            return {
                "lead_id": lead_id,
                "icp_score": final.get("icp_score", 0.5),
                "lead_data": final.get("lead_data", {}),
                "kb_context": final.get("kb_context", []),
                "interaction_history": final.get("interaction_history", []),
            }
        except Exception as exc:
            import logging as _lg
            _lg.getLogger(__name__).warning("[PreCall] Graph failed: %s", exc)
    # Fallback: run nodes sequentially
    state = knowledge_node(state)
    state = researcher_node(state)
    return {
        "lead_id": lead_id,
        "icp_score": state["icp_score"],
        "lead_data": state["lead_data"],
        "kb_context": state["kb_context"],
        "interaction_history": state["interaction_history"],
    }
