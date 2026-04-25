"""
Rio CRM — Master Multi-Agent Orchestrator.

Wires all 9 specialised agents (knowledge, enrichment, researcher, post_call,
coach, ism, campaign, quote, analytics) into a single LangGraph StateGraph
coordinated by the supervisor.

Entry points
------------
run_pre_call(lead_id, company_id, actor_user_id)
    -> Run knowledge + researcher before an outbound call.

run_post_call(lead_id, company_id, actor_user_id, ...)
    -> Run post_call + coach + ism after a call ends.

run_agent(agent_name, query, company_id, actor_user_id)
    -> Invoke any single agent directly by name.

ask(query, company_id, actor_user_id)
    -> Let the supervisor decide which agent(s) to run for a freeform request.
"""
from __future__ import annotations

import logging
from typing import Any, List, Optional

from sqlmodel import Session

from database import engine
from agents.state import RioState, empty_state
from agents.supervisor import supervisor_node, AGENT_LIST
from utils.tracing import traceable_async
from utils.retry import with_fallback, get_breaker

logger = logging.getLogger(__name__)


# Agent registry — maps name -> importable module

_AGENT_MODULES: dict[str, str] = {
    "knowledge":  "agents.knowledge",
    "enrichment": "agents.enrichment",
    "researcher": "agents.researcher",
    "post_call":  "agents.post_call",
    "coach":      "agents.coach",
    "ism":        "agents.ism",
    "campaign":   "agents.campaign",
    "quote":      "agents.quote",
    "analytics":  "agents.analytics",
    # Side-effecting send executor — invoked by the worker when it claims an
    # AgentTask with assigned_agent="send". Not LLM-driven; just dispatches
    # to communication_service based on task_type.
    "send":       "agents.send",
    # Webhook audit sink — Phase 1 no-op; Phase 2 (Week 3+) replaces with
    # per-event-type handlers reading from AgentTask.input_json["payload"].
    "webhook_sink": "agents.webhook_sink",
    # Week 7 — three-agent split. outreacher + closer carry ISM dispatch + deal
    # closure; reply_classifier buckets inbound replies into roadmap intents.
    "outreacher":       "agents.outreacher",
    "closer":           "agents.closer",
    "reply_classifier": "agents.reply_classifier",
}


def _get_agent_module(name: str):
    import importlib
    mod_path = _AGENT_MODULES.get(name)
    if not mod_path:
        raise ValueError(f"Unknown agent: {name!r}. Valid: {list(_AGENT_MODULES)}")
    return importlib.import_module(mod_path)


# Build the full multi-agent StateGraph

def _build_orchestrator_graph(session: Session, company_id: int):
    """
    Compile the supervisor-coordinated multi-agent StateGraph.

    Each agent is a node that:
    1. Reads from RioState (lead_id, company_id, call_transcript, etc.)
    2. Calls create_react_agent internally with the company LLM
    3. Writes results back to state["agent_results"][<name>]
    """
    try:
        from langgraph.graph import StateGraph, END
        from langchain_core.messages import HumanMessage
        from agents.llm_factory import get_agent_llm
        from agents.checkpointer import get_checkpointer
    except ImportError as exc:
        raise RuntimeError(f"LangGraph/LangChain not available: {exc}") from exc

    llm = get_agent_llm(session, company_id)
    agent_names = [a for a in AGENT_LIST if a != "FINISH"]

    def _make_node(agent_name: str):
        """Build an async StateGraph node that delegates to a create_react_agent."""
        mod = _get_agent_module(agent_name)

        async def _node(state: RioState) -> RioState:
            state["current_agent"] = agent_name
            lead_id = state.get("lead_id")
            transcript_hint = " (transcript available)" if state.get("call_transcript") else ""
            query = (
                f"Company {company_id}, lead {lead_id}{transcript_hint}. "
                f"Perform your {agent_name} responsibilities for this lead."
            )
            try:
                agent = mod.create_agent(llm, company_id)
                config = {"configurable": {"thread_id": f"{agent_name}_{company_id}_{lead_id}"}}
                result = await agent.ainvoke(
                    {"messages": [HumanMessage(content=query)]},
                    config=config,
                )
                output = result["messages"][-1].content
                state["agent_results"][agent_name] = {"output": output}
                logger.info("[Orchestrator] %s completed for lead %s", agent_name, lead_id)
            except Exception as exc:
                logger.warning("[Orchestrator] %s node failed: %s", agent_name, exc)
                state["errors"].append(f"{agent_name}: {exc}")
            state["next_agent"] = ""
            return state

        _node.__name__ = f"{agent_name}_node"
        return _node

    wf = StateGraph(RioState)
    wf.add_node("supervisor", supervisor_node)
    for name in agent_names:
        wf.add_node(name, _make_node(name))

    def _route(state: RioState) -> str:
        nxt = state.get("next_agent", "FINISH")
        return END if (nxt == "FINISH" or nxt not in agent_names) else nxt

    wf.set_entry_point("supervisor")
    wf.add_conditional_edges(
        "supervisor",
        _route,
        {n: n for n in agent_names} | {END: END},
    )
    for name in agent_names:
        wf.add_edge(name, "supervisor")

    return wf.compile(checkpointer=get_checkpointer())


# Public entry points

@traceable_async(name="orchestrator_run_pre_call", run_type="chain", tags=["pre_call", "orchestrator"])
async def run_pre_call(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
) -> dict:
    """
    Run the pre-call workflow (knowledge -> researcher) via the orchestrator.

    Delegates to pre_call_graph for efficiency; falls back to the full
    orchestrator graph if that fails.

    Args:
        lead_id: ID of the lead being called.
        company_id: Tenant ID.
        actor_user_id: ID of the SDR initiating the call.
    """
    try:
        from agents.pre_call_graph import run_pre_call_workflow
        return await run_pre_call_workflow(lead_id, company_id, actor_user_id)
    except Exception as exc:
        logger.warning("[Orchestrator] pre_call_graph failed, falling back: %s", exc)

    state = empty_state(company_id=company_id, actor_user_id=actor_user_id, lead_id=lead_id)
    state["agent_results"]["_task_type"] = "pre_call"

    with Session(engine) as session:
        graph = _build_orchestrator_graph(session, company_id)

    config = {"configurable": {"thread_id": f"pre_call_{company_id}_{lead_id}"}}
    try:
        final = await graph.ainvoke(state, config=config)
        return {
            "lead_id": lead_id,
            "icp_score": final.get("icp_score", 0.5),
            "lead_data": final.get("lead_data", {}),
            "kb_context": final.get("kb_context", []),
            "interaction_history": final.get("interaction_history", []),
            "errors": final.get("errors", []),
        }
    except Exception as exc:
        logger.error("[Orchestrator] run_pre_call failed: %s", exc)
        return {"lead_id": lead_id, "icp_score": 0.5, "lead_data": {}, "kb_context": [], "errors": [str(exc)]}


@traceable_async(name="orchestrator_run_post_call", run_type="chain", tags=["post_call", "orchestrator"])
async def run_post_call(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
    lead_name: str = "",
    lead_email: str = "",
    call_transcript: str = "",
    call_duration: int = 0,
    call_outcome: str = "neutral",
    sentiment: str = "neutral",
    icp_score: float = 0.5,
    pain_points: List[str] = None,
    questions_asked: List[str] = None,
    bant_answers: dict = None,
) -> dict:
    """
    Run the post-call workflow (post_call -> coach -> ism) via the orchestrator.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the SDR.
        lead_name: Lead display name.
        lead_email: Lead email address.
        call_transcript: Full call transcript.
        call_duration: Duration in seconds.
        call_outcome: positive / neutral / not_qualified.
        sentiment: positive / neutral / negative.
        icp_score: Lead ICP fit score (0.0-1.0).
        pain_points: Pain points detected in transcript.
        questions_asked: Questions the lead raised.
        bant_answers: BANT dict (budget/authority/need/timeline).
    """
    try:
        from agents.post_call_graph import run_post_call_workflow
        return await run_post_call_workflow(
            lead_id=lead_id, company_id=company_id, actor_user_id=actor_user_id,
            lead_name=lead_name, lead_email=lead_email, call_transcript=call_transcript,
            call_duration=call_duration, call_outcome=call_outcome, sentiment=sentiment,
            icp_score=icp_score, pain_points=pain_points or [],
            questions_asked=questions_asked or [], bant_answers=bant_answers or {},
        )
    except Exception as exc:
        logger.warning("[Orchestrator] post_call_graph failed, falling back: %s", exc)

    state = empty_state(company_id=company_id, actor_user_id=actor_user_id, lead_id=lead_id)
    state.update({
        "lead_data": {"name": lead_name, "email": lead_email},
        "call_transcript": call_transcript,
        "call_duration": call_duration,
        "call_outcome": call_outcome,
        "sentiment": sentiment,
        "icp_score": icp_score,
        "pain_points": pain_points or [],
        "questions_asked": questions_asked or [],
        "bant_answers": bant_answers or {},
        "agent_results": {"_task_type": "post_call"},
    })

    with Session(engine) as session:
        graph = _build_orchestrator_graph(session, company_id)

    config = {"configurable": {"thread_id": f"post_call_{company_id}_{lead_id}"}}
    try:
        final = await graph.ainvoke(state, config=config)
        return {
            "lead_id": lead_id,
            "next_action": final.get("agent_results", {}).get("post_call", {}).get("next", ""),
            "follow_up_sent": "book_demo" in final.get("agent_results", {}),
            "errors": final.get("errors", []),
        }
    except Exception as exc:
        logger.error("[Orchestrator] run_post_call failed: %s", exc)
        return {"lead_id": lead_id, "errors": [str(exc)]}


@traceable_async(name="orchestrator_run_agent", run_type="chain", tags=["orchestrator"])
async def run_agent(
    agent_name: str,
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
    **kwargs: Any,
) -> dict:
    """
    Invoke any single agent by name with a natural-language query.

    Args:
        agent_name: One of: knowledge, enrichment, researcher, post_call,
                    coach, ism, campaign, quote, analytics.
        query: Natural-language instruction or question for the agent.
        company_id: Tenant ID.
        actor_user_id: ID of the requesting user.
        thread_id: Optional LangGraph thread ID for persistent memory.
        **kwargs: Extra args forwarded to the agent's run() function
                  (e.g. lead_id for researcher/ism/enrichment agents).
    """
    import inspect
    mod = _get_agent_module(agent_name)

    sig = inspect.signature(mod.run)
    params = set(sig.parameters.keys())
    call_kwargs: dict = {"company_id": company_id, "actor_user_id": actor_user_id}
    if thread_id:
        call_kwargs["thread_id"] = thread_id
    if "query" in params:
        call_kwargs["query"] = query
    for k, v in kwargs.items():
        if k in params:
            call_kwargs[k] = v

    return await with_fallback(
        primary=lambda: mod.run(**call_kwargs),
        fallback=lambda: {"output": f"Agent {agent_name!r} is temporarily unavailable.", "errors": []},
        agent_name=agent_name,
        max_attempts=2,
        base_delay=0.5,
    )


@traceable_async(name="orchestrator_ask", run_type="chain", tags=["orchestrator", "supervisor"])
async def ask(
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    lead_id: int | None = None,
    thread_id: str | None = None,
) -> dict:
    """
    Ask Rio a freeform question — the supervisor decides which agent(s) to route to.

    Args:
        query: Any sales question or instruction (e.g. "What are the top objections?").
        company_id: Tenant ID.
        actor_user_id: ID of the requesting user.
        lead_id: Optional lead context to inject into state.
        thread_id: Optional LangGraph thread ID for persistent memory.
    """
    from langchain_core.messages import HumanMessage
    state = empty_state(company_id=company_id, actor_user_id=actor_user_id, lead_id=lead_id)
    state["messages"] = [HumanMessage(content=query)]
    cfg = {"configurable": {"thread_id": thread_id or f"ask_{company_id}_{actor_user_id}"}}

    async def _run():
        # Graph build is inside _run so LLM/import errors are caught by with_fallback
        with Session(engine) as session:
            graph = _build_orchestrator_graph(session, company_id)
        final = await graph.ainvoke(state, config=cfg)
        msgs = final.get("messages", [])
        output = msgs[-1].content if msgs else ""
        return {
            "output": output,
            "agents_run": list(final.get("agent_results", {}).keys()),
            "errors": final.get("errors", []),
        }

    return await with_fallback(
        primary=_run,
        fallback=lambda: {"output": "Rio is temporarily unavailable. Please try again shortly.", "agents_run": [], "errors": []},
        agent_name="orchestrator_ask",
        max_attempts=2,
        base_delay=1.0,
    )
