"""
Supervisor - the routing brain of the Rio multi-agent system.
"""
from __future__ import annotations
import logging
from langchain_core.messages import HumanMessage, SystemMessage
from .state import RioState
from utils.tracing import traceable
logger = logging.getLogger(__name__)
AGENT_LIST = ["knowledge","researcher","enrichment","post_call","coach","ism","campaign","quote","analytics","FINISH"]
_TASK_SEQUENCES: dict[str, list[str]] = {
    "pre_call":  ["knowledge", "researcher"],
    "post_call": ["post_call", "coach", "ism"],
    "enrich":    ["enrichment"],
    "search":    ["knowledge"],
    "quote":     ["quote"],
    "analytics": ["analytics"],
    "campaign":  ["campaign"],
}
_SUPERVISOR_SYSTEM_PROMPT = """You are the Rio CRM orchestrator. Decide which agent runs next.
Available: knowledge, researcher, enrichment, post_call, coach, ism, campaign, quote, analytics, FINISH.
Respond with exactly one word."""
def _next_in_sequence(sequence, completed):
    for agent in sequence:
        if agent not in completed:
            return agent
    return "FINISH"
def _llm_route(state):
    try:
        from database import engine
        from sqlmodel import Session
        from .llm_factory import get_agent_llm
        context = f"lead_id={state.get('lead_id')}, has_transcript={'yes' if state.get('call_transcript') else 'no'}, agents_run={list(state.get('agent_results',{}).keys())}"
        msgs = [SystemMessage(content=_SUPERVISOR_SYSTEM_PROMPT), HumanMessage(content=f"State: {context}")]
        with Session(engine) as session:
            llm = get_agent_llm(session, state["company_id"])
        resp = llm.invoke(msgs)
        agent = resp.content.strip().split()[0]
        return agent if agent in AGENT_LIST else "FINISH"
    except Exception as exc:
        logger.error("[Supervisor] LLM routing failed: %s", exc)
        return "FINISH"
@traceable(name="supervisor_node", run_type="chain", tags=["supervisor"])
def supervisor_node(state: RioState) -> RioState:
    if state.get("next_agent") and state["next_agent"] not in ("", "supervisor"):
        return state
    task_type = state.get("agent_results", {}).get("_task_type", "")
    if task_type in _TASK_SEQUENCES:
        completed = set(state.get("agent_results", {}).keys()) - {"_task_type"}
        state["next_agent"] = _next_in_sequence(_TASK_SEQUENCES[task_type], completed)
        return state
    state["next_agent"] = _llm_route(state)
    return state
def add_supervisor_routing(workflow, agent_nodes):
    from langgraph.graph import END
    def _route(state):
        nxt = state.get("next_agent", "FINISH")
        return END if (nxt == "FINISH" or nxt not in agent_nodes) else nxt
    workflow.add_node("supervisor", supervisor_node)
    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges("supervisor", _route, {n: n for n in agent_nodes} | {END: END})
    for node in agent_nodes:
        workflow.add_edge(node, "supervisor")
