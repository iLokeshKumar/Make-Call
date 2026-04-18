from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)


@tool
def get_engagement_summary(company_id: int, days: int = 30) -> str:
    """Get an engagement summary for the last N days (calls, emails, opens, replies).

    Args:
        company_id: Tenant ID.
        days: Lookback window in days (default 30).
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.analytics.analytics_service import get_engagement_summary as _get
        with Session(engine) as session:
            result = _get(session=session, company_id=company_id, days=days)
        return str(result)
    except Exception as exc:
        logger.warning("[AnalyticsAgent] get_engagement_summary failed: %s", exc)
        return f"Could not fetch engagement summary: {exc}"


@tool
def get_call_conversion_summary(company_id: int, days: int = 30) -> str:
    """Get call-to-conversion metrics: answer rates, positive outcomes, demo bookings.

    Args:
        company_id: Tenant ID.
        days: Lookback window in days (default 30).
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.analytics.analytics_service import get_call_conversion_summary as _get
        with Session(engine) as session:
            result = _get(session=session, company_id=company_id, days=days)
        return str(result)
    except Exception as exc:
        logger.warning("[AnalyticsAgent] get_call_conversion_summary failed: %s", exc)
        return f"Could not fetch call conversion summary: {exc}"


@tool
def get_pipeline_funnel(company_id: int) -> str:
    """Get lead counts at each ISM stage (funnel view).

    Args:
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session, select, func
        from models.models import Lead
        with Session(engine) as session:
            rows = session.exec(
                select(Lead.ism_stage, func.count(Lead.id).label("count"))
                .where(Lead.company_id == company_id)
                .group_by(Lead.ism_stage)
            ).all()
        return str({r[0] or "unknown": r[1] for r in rows})
    except Exception as exc:
        logger.warning("[AnalyticsAgent] get_pipeline_funnel failed: %s", exc)
        return f"Could not fetch pipeline funnel: {exc}"


@tool
def evaluate_alerts(company_id: int) -> str:
    """Check all analytics alerts for a company and return any that are firing.

    Args:
        company_id: Tenant ID.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from services.analytics.analytics_service import evaluate_alerts as _eval
        with Session(engine) as session:
            result = _eval(session=session, company_id=company_id)
        return str(result)
    except Exception as exc:
        logger.warning("[AnalyticsAgent] evaluate_alerts failed: %s", exc)
        return f"Could not evaluate alerts: {exc}"


ANALYTICS_TOOLS = [get_engagement_summary, get_call_conversion_summary, get_pipeline_funnel, evaluate_alerts]


@traceable(name="analytics_node", run_type="chain", tags=['analytics'])
def analytics_node(state: dict) -> dict:
    """LangGraph node: snapshot key pipeline metrics into agent_results."""
    company_id = state.get("company_id", 0)
    if not company_id:
        return state
    try:
        funnel = get_pipeline_funnel.invoke({"company_id": company_id})
        state.setdefault("agent_results", {})["analytics"] = {"funnel": funnel}
    except Exception as exc:
        logger.warning("[AnalyticsAgent] analytics_node failed: %s", exc)
        state.setdefault("errors", []).append(f"analytics_node: {exc}")
    return state


_ANALYTICS_SYSTEM_PROMPT = (
    "You are the Analytics Agent for Rio CRM.\n"
    "You answer questions about pipeline performance and sales metrics.\n\n"
    "Your tools:\n"
    "- get_pipeline_funnel: lead counts at each ISM stage\n"
    "- get_engagement_summary: calls, emails, opens, replies over N days\n"
    "- get_call_conversion_summary: answer rates, positive outcomes, demo bookings\n"
    "- evaluate_alerts: check if any analytics alert thresholds are firing\n\n"
    "Rules:\n"
    "- Always include numbers with context (e.g. 42 leads in negotiation).\n"
    "- If asked about trends, fetch data for both current and prior period.\n"
    "- Flag any firing alerts prominently at the top of your response."
)


def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_checkpointer
    return create_agent(
        llm,
        tools=ANALYTICS_TOOLS,
        system_prompt=_ANALYTICS_SYSTEM_PROMPT,
        checkpointer=get_checkpointer(),
    )


@traceable_async(name="run_analytics_agent", run_type="chain", tags=["analytics"])
async def run(
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Answer a natural-language analytics question about the pipeline.

    Args:
        query: Question (e.g. "How many demos were booked this week?").
        company_id: Tenant ID.
        actor_user_id: ID of the requesting user.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    config = {"configurable": {"thread_id": thread_id or f"analytics_{company_id}"}}
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
        logger.warning("[AnalyticsAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}
