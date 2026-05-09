from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)


@tool
def enroll_lead_in_campaign(lead_ids: list, campaign_id: int, company_id: int, actor_user_id: int) -> str:
    """Enroll one or more leads into a drip campaign.

    Args:
        lead_ids: List of lead IDs to enroll.
        campaign_id: ID of the campaign.
        company_id: Tenant ID.
        actor_user_id: ID of the user performing the enrollment.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.campaign.campaign_service import enroll_leads
        with Session(engine) as session:
            result = enroll_leads(
                session=session, campaign_id=campaign_id,
                lead_ids=lead_ids, company_id=company_id, actor_user_id=actor_user_id,
            )
        return f"Enrolled {len(lead_ids)} lead(s) into campaign {campaign_id}."
    except Exception as exc:
        logger.warning("[CampaignAgent] enroll_lead_in_campaign failed: %s", exc)
        return f"Enrollment failed: {exc}"


@tool
def get_campaign_performance(campaign_id: int, company_id: int) -> str:
    """Get email performance metrics for a campaign (opens, clicks, replies).

    Args:
        campaign_id: ID of the campaign.
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.analytics.analytics_service import get_campaign_email_report
        with Session(engine) as session:
            result = get_campaign_email_report(session=session, company_id=company_id, campaign_id=campaign_id)
        return str(result)
    except Exception as exc:
        logger.warning("[CampaignAgent] get_campaign_performance failed: %s", exc)
        return f"Could not fetch campaign performance: {exc}"


@tool
def list_active_campaigns(company_id: int) -> str:
    """List all campaigns for a company.

    Args:
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.campaign.campaign_service import list_campaigns
        with Session(engine) as session:
            result = list_campaigns(session=session, company_id=company_id)
        return str(result)
    except Exception as exc:
        logger.warning("[CampaignAgent] list_active_campaigns failed: %s", exc)
        return f"Could not list campaigns: {exc}"


CAMPAIGN_TOOLS = [enroll_lead_in_campaign, get_campaign_performance, list_active_campaigns]


@traceable(name="campaign_node", run_type="chain", tags=['campaign'])
def campaign_node(state: dict) -> dict:
    """LangGraph node: snapshot campaign list into agent_results."""
    company_id = state.get("company_id", 0)
    call_outcome = state.get("call_outcome") or ""

    if not company_id or call_outcome == "not_qualified":
        return state

    campaigns_str = list_active_campaigns.invoke({"company_id": company_id})
    state.setdefault("agent_results", {})["campaign"] = {"campaigns": campaigns_str}
    return state


_CAMPAIGN_SYSTEM_PROMPT = (
    "You are the Campaign Agent for Rio CRM.\n"
    "You manage drip campaigns and email sequences.\n\n"
    "Your tools:\n"
    "- list_active_campaigns: see all campaigns for the company\n"
    "- enroll_lead_in_campaign: add leads to a campaign\n"
    "- get_campaign_performance: check open/click/reply rates\n\n"
    "Rules:\n"
    "- Always call list_active_campaigns first to confirm the campaign exists.\n"
    "- Enroll leads only once -- check if already enrolled where possible.\n"
    "- Report performance metrics clearly with percentages."
)


async def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_async_checkpointer
    return create_agent(
        llm,
        tools=CAMPAIGN_TOOLS,
        system_prompt=_CAMPAIGN_SYSTEM_PROMPT,
        checkpointer=await get_async_checkpointer(),
    )


@traceable_async(name="run_campaign_agent", run_type="chain", tags=["campaign"])
async def run(
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Run the Campaign Agent with a natural-language instruction.

    Args:
        query: Instruction (e.g. "Enroll lead 42 in the winter outreach campaign").
        company_id: Tenant ID.
        actor_user_id: ID of the requesting user.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    config = {"configurable": {"thread_id": thread_id or f"campaign_{company_id}"}}
    with Session(engine) as session:
        llm = get_agent_llm(session, company_id)
    agent = await create_agent(llm, company_id)
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
        return {"output": result["messages"][-1].content, "errors": []}
    except Exception as exc:
        logger.warning("[CampaignAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}
