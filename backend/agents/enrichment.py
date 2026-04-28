from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)


@tool
def enrich_lead(lead_id: int, company_id: int, actor_user_id: int) -> str:
    """Enrich a lead using Apollo.io and other data sources.

    Args:
        lead_id: ID of the lead to enrich.
        company_id: Tenant ID.
        actor_user_id: ID of the user triggering the enrichment.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.leads.demand_generation_service import enrich_lead_if_needed
        with Session(engine) as session:
            enrich_lead_if_needed(
                session=session, company_id=company_id,
                actor_user_id=actor_user_id, lead_id=lead_id,
            )
        return f"Lead {lead_id} enrichment complete."
    except Exception as exc:
        logger.warning("[EnrichmentAgent] enrich_lead failed: %s", exc)
        return f"Enrichment failed: {exc}"


@tool
def score_lead_icp(lead_id: int, company_id: int) -> str:
    """Compute and persist an ICP fit score (0.0-1.0) for a lead.

    Args:
        lead_id: ID of the lead to score.
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.leads.demand_generation_service import score_lead as _score
        with Session(engine) as session:
            result = _score(session=session, company_id=company_id, lead_id=lead_id)
        score = float(result.get("score") or 0.5)
        return f"ICP score for lead {lead_id}: {score:.2f}"
    except Exception as exc:
        logger.warning("[EnrichmentAgent] score_lead failed: %s", exc)
        return f"Scoring failed: {exc}"


@tool
def choose_outreach_strategy(lead_id: int, company_id: int) -> str:
    """Recommend next outreach channel for a lead based on ICP score + history.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.leads.demand_generation_service import score_lead as _score, choose_outreach_strategy as _choose
        with Session(engine) as session:
            score_result = _score(session=session, company_id=company_id, lead_id=lead_id)
            result = _choose(session=session, company_id=company_id, lead_id=lead_id, score_payload=score_result)
        return str(result)
    except Exception as exc:
        logger.warning("[EnrichmentAgent] choose_outreach_strategy failed: %s", exc)
        return f"Strategy selection failed: {exc}"


ENRICHMENT_TOOLS = [enrich_lead, score_lead_icp, choose_outreach_strategy]


@traceable(name="enrichment_node", run_type="chain", tags=['enrichment'])
def enrichment_node(state: dict) -> dict:
    """LangGraph node: enrich lead and refresh ICP score in state."""
    lead_id = state.get("lead_id")
    company_id = state.get("company_id", 0)
    actor_user_id = state.get("actor_user_id", 0)

    if not lead_id:
        state.setdefault("errors", []).append("enrichment_node: lead_id missing")
        return state

    enrich_lead.invoke({"lead_id": lead_id, "company_id": company_id, "actor_user_id": actor_user_id})

    try:
        from database import engine
        from sqlmodel import Session
        from services.leads.demand_generation_service import score_lead as _score
        with Session(engine) as session:
            result = _score(session=session, company_id=company_id, lead_id=lead_id)
        state["icp_score"] = float(result.get("score") or 0.5)
        state.setdefault("agent_results", {})["enrichment"] = result
    except Exception as exc:
        logger.warning("[EnrichmentAgent] node scoring failed: %s", exc)
        state.setdefault("errors", []).append(f"enrichment_node: {exc}")

    return state


_ENRICHMENT_SYSTEM_PROMPT = (
    "You are the Enrichment Agent for Rio CRM.\n"
    "Your job: enrich leads with missing contact/company data via Apollo\n"
    "and compute an ICP (Ideal Customer Profile) fit score.\n\n"
    "Rules:\n"
    "- Always call enrich_lead before score_lead_icp so scoring has fresh data.\n"
    "- If enrichment fails, still call score_lead_icp -- it scores with what is there.\n"
    "- Return a brief summary: {lead_id, icp_score, recommended_channel}.\n"
    "- Use choose_outreach_strategy to pick the next touchpoint."
)


def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_checkpointer
    return create_agent(
        llm,
        tools=ENRICHMENT_TOOLS,
        system_prompt=_ENRICHMENT_SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


@traceable_async(name="run_enrichment_agent", run_type="chain", tags=["enrichment"])
async def run(
    lead_id: int,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Enrich a lead and compute its ICP score.

    Args:
        lead_id: ID of the lead to enrich and score.
        company_id: Tenant ID.
        actor_user_id: ID of the user triggering enrichment.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    query = f"Enrich and score lead {lead_id} for company {company_id}. actor_user_id={actor_user_id}."
    config = {"configurable": {"thread_id": thread_id or f"enrichment_{company_id}_{lead_id}"}}
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
        logger.warning("[EnrichmentAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}
