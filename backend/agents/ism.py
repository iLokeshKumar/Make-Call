"""
ISM Agent — Intelligent Sales-Motion stage progression.

Delegates to ism_orchestrator.run_ism_cycle() to pick the best outreach
channel for the current ISM stage and dispatch the action.
"""
from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)

ISM_STAGES = ["new", "contacted", "engaged", "quote_sent", "negotiation", "closed_won", "closed_lost"]


@tool
def advance_ism_stage(lead_id: int, company_id: int, actor_user_id: int) -> str:
    """Run one ISM cycle: advance the lead's stage and dispatch the best outreach channel.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the user initiating the cycle.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from agents.ism_orchestrator import run_ism_cycle
        with Session(engine) as session:
            result = run_ism_cycle(
                session=session, company_id=company_id,
                lead_id=lead_id, actor_user_id=actor_user_id,
            )
        return str(result)
    except Exception as exc:
        logger.warning("[ISMAgent] advance_ism_stage failed: %s", exc)
        return f"ISM cycle failed: {exc}"


@tool
def get_ism_stage(lead_id: int, company_id: int) -> str:
    """Get the current ISM stage for a lead.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session, select
        from models.models import Lead
        with Session(engine) as session:
            lead = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
            ).first()
            if not lead:
                return f"Lead {lead_id} not found."
            return lead.ism_stage or "new"
    except Exception as exc:
        return f"Could not fetch ISM stage: {exc}"


@tool
def set_ism_stage(lead_id: int, company_id: int, new_stage: str, actor_user_id: int = 0) -> str:
    """Manually set the ISM stage for a lead.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        new_stage: Target stage (new/contacted/engaged/quote_sent/negotiation/closed_won/closed_lost).
        actor_user_id: ID of the user making the change.
    """
    if new_stage not in ISM_STAGES:
        return f"Invalid stage. Valid stages: {', '.join(ISM_STAGES)}"
    try:
        from database import engine
        from sqlmodel import Session, select
        from models.models import Lead
        with Session(engine) as session:
            lead = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
            ).first()
            if not lead:
                return f"Lead {lead_id} not found."
            lead.ism_stage = new_stage
            session.add(lead)
            session.commit()
        return f"Lead {lead_id} ISM stage set to '{new_stage}'."
    except Exception as exc:
        logger.warning("[ISMAgent] set_ism_stage failed: %s", exc)
        return f"Stage update failed: {exc}"


ISM_TOOLS = [advance_ism_stage, get_ism_stage, set_ism_stage]


@traceable(name="ism_node", run_type="chain", tags=['ism'])
def ism_node(state: dict) -> dict:
    """LangGraph node: run ISM cycle and record result in state."""
    lead_id = state.get("lead_id")
    company_id = state.get("company_id", 0)
    actor_user_id = state.get("actor_user_id", 0)

    if not lead_id:
        state.setdefault("errors", []).append("ism_node: lead_id missing")
        return state

    result = advance_ism_stage.invoke({
        "lead_id": lead_id, "company_id": company_id, "actor_user_id": actor_user_id,
    })
    state.setdefault("agent_results", {})["ism"] = {"result": result}
    return state


_ISM_SYSTEM_PROMPT = (
    "You are the ISM (Intelligent Sales-Motion) Agent for Rio CRM.\n"
    "You manage lead progression through the sales funnel:\n"
    "  new -> contacted -> engaged -> quote_sent -> negotiation -> closed_won / closed_lost\n\n"
    "Your tools:\n"
    "- advance_ism_stage: run a full ISM cycle (chooses channel, dispatches action)\n"
    "- get_ism_stage: check current stage\n"
    "- set_ism_stage: manually override the stage\n\n"
    "Rules:\n"
    "- Always check get_ism_stage before deciding to advance.\n"
    "- Use advance_ism_stage for normal progression -- it picks the best outreach channel.\n"
    "- Only use set_ism_stage when explicitly instructed to override.\n"
    "- Never advance a lead that is already closed_won or closed_lost."
)


def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_checkpointer
    return create_agent(
        llm,
        tools=ISM_TOOLS,
        system_prompt=_ISM_SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


@traceable_async(name="run_ism_agent", run_type="chain", tags=["ism"])
async def run(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
    instruction: str = "",
    thread_id: str | None = None,
) -> dict:
    """Run the ISM Agent for a lead -- advance stage and dispatch outreach.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the user triggering the cycle.
        instruction: Optional override instruction (e.g. "move to negotiation").
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    query = instruction or (
        f"Run ISM cycle for lead {lead_id} (company {company_id}, actor {actor_user_id}). "
        "Check current stage then advance if appropriate."
    )
    config = {"configurable": {"thread_id": thread_id or f"ism_{company_id}_{lead_id}"}}
    with Session(engine) as session:
        llm = get_agent_llm(session, company_id)
    agent = create_agent(llm, company_id)
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
        return {"output": result["messages"][-1].content, "errors": []}
    except Exception as exc:
        logger.warning("[ISMAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}
