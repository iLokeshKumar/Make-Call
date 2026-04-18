from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)


@tool
def get_lead_profile(lead_id: int, company_id: int) -> str:
    """Fetch a lead's full profile including company, industry, and contact info.

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
                return f"Lead {lead_id} not found for company {company_id}."
            return str({
                "id": lead.id,
                "name": lead.name,
                "email": lead.email,
                "phone": lead.normalized_phone,
                "job_title": lead.job_title,
                "industry": lead.industry,
                "ism_stage": lead.ism_stage,
                "icp_score": lead.icp_score,
                "company_name": lead.company_name,
            })
    except Exception as exc:
        logger.warning("[ResearcherAgent] get_lead_profile failed: %s", exc)
        return f"Could not fetch lead profile: {exc}"


@tool
def get_interaction_history(lead_id: int, company_id: int, limit: int = 10) -> str:
    """Retrieve the most recent interactions for a lead.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        limit: Max interactions to return (default 10).
    """
    try:
        from database import engine
        from sqlmodel import Session, select
        from models.models import Interaction
        with Session(engine) as session:
            rows = session.exec(
                select(Interaction)
                .where(Interaction.lead_id == lead_id, Interaction.company_id == company_id)
                .order_by(Interaction.started_at.desc())
                .limit(limit)
            ).all()
            return str([{
                "id": r.id, "type": r.interaction_type,
                "started_at": str(r.started_at), "outcome": r.outcome, "summary": r.summary,
            } for r in rows])
    except Exception as exc:
        logger.warning("[ResearcherAgent] get_interaction_history failed: %s", exc)
        return f"Could not fetch interactions: {exc}"


RESEARCHER_TOOLS = [get_lead_profile, get_interaction_history]


@traceable(name="researcher_node", run_type="chain", tags=['researcher'])
def researcher_node(state: dict) -> dict:
    """LangGraph node: populate lead_data and interaction_history in state."""
    lead_id = state.get("lead_id")
    company_id = state.get("company_id", 0)
    actor_user_id = state.get("actor_user_id", 0)

    if not lead_id:
        state.setdefault("errors", []).append("researcher_node: lead_id missing")
        return state

    try:
        from database import engine
        from sqlmodel import Session, select
        from models.models import Lead, Interaction
        with Session(engine) as session:
            lead = session.exec(
                select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)
            ).first()
            if lead:
                state["lead_data"] = {
                    "id": lead.id,
                    "name": lead.name,
                    "email": lead.email, "phone": lead.normalized_phone,
                    "job_title": lead.job_title,
                    "industry": lead.industry, "ism_stage": lead.ism_stage,
                    "icp_score": float(lead.icp_score or 0.5),
                    "company_name": lead.company_name,
                }
                state["icp_score"] = float(lead.icp_score or 0.5)

            rows = session.exec(
                select(Interaction)
                .where(Interaction.lead_id == lead_id, Interaction.company_id == company_id)
                .order_by(Interaction.started_at.desc()).limit(10)
            ).all()
            state["interaction_history"] = [{
                "id": r.id, "type": r.interaction_type,
                "started_at": str(r.started_at), "outcome": r.outcome, "summary": r.summary,
            } for r in rows]

            try:
                from services.leads.demand_generation_service import enrich_lead_if_needed, score_lead
                enrich_lead_if_needed(session=session, company_id=company_id,
                                      actor_user_id=actor_user_id, lead_id=lead_id)
                result = score_lead(session=session, company_id=company_id, lead_id=lead_id)
                state["icp_score"] = float(result.get("score") or state.get("icp_score", 0.5))
                state.setdefault("agent_results", {})["researcher"] = result
            except Exception as exc:
                logger.warning("[ResearcherAgent] enrichment/scoring failed: %s", exc)

    except Exception as exc:
        logger.warning("[ResearcherAgent] node failed: %s", exc)
        state.setdefault("errors", []).append(f"researcher_node: {exc}")

    return state


_RESEARCHER_SYSTEM_PROMPT = (
    "You are the Researcher Agent for Rio CRM.\n"
    "Your job: compile a full pre-call dossier on a lead before an outbound call.\n\n"
    "Steps you MUST take:\n"
    "1. Call get_lead_profile to fetch current lead data.\n"
    "2. Call get_interaction_history to understand past touchpoints.\n"
    "3. Summarise: who they are, last interaction, what was discussed, suggested talking points.\n\n"
    "Output a concise briefing an SDR can read in 30 seconds."
)


def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_checkpointer
    return create_agent(
        llm,
        tools=RESEARCHER_TOOLS,
        system_prompt=_RESEARCHER_SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


@traceable_async(name="run_researcher_agent", run_type="chain", tags=["researcher"])
async def run(
    lead_id: int,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Compile a pre-call briefing for a lead.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the requesting user.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    query = f"Prepare a pre-call briefing for lead {lead_id} (company {company_id})."
    config = {"configurable": {"thread_id": thread_id or f"researcher_{company_id}_{lead_id}"}}
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
        logger.warning("[ResearcherAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}
