from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async
from agents._format_utils import to_compact

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
            return to_compact({
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
            return to_compact([{
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


async def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_async_checkpointer
    return create_agent(
        llm,
        tools=RESEARCHER_TOOLS,
        system_prompt=_RESEARCHER_SYSTEM_PROMPT,
        checkpointer=await get_async_checkpointer(),
    )


def _get_qualify_threshold(session, company_id: int) -> float:
    """Per-company ICP qualification threshold.  Default 0.5."""
    try:
        from credentials_service import get_company_setting_value
        raw = get_company_setting_value(session, company_id, "COMPANY_ICP_QUALIFY_THRESHOLD")
        if raw is None or str(raw).strip() == "":
            return 0.5
        return float(str(raw).strip())
    except Exception as exc:  # noqa: BLE001
        logger.debug("[ResearcherAgent] threshold lookup failed: %s", exc)
        return 0.5


def _coerce_list(value) -> str | None:
    """Normalise list-or-string fields to a comma-separated string, or None."""
    if value is None:
        return None
    if isinstance(value, list):
        joined = ", ".join(str(v).strip() for v in value if v)
        return joined or None
    s = str(value).strip()
    return s or None


def _persist_signals_and_qualify(
    session,
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    scoring_result: dict,
    icp_score: float,
) -> dict:
    """Persist LeadRequirement from researcher extraction + qualify or disqualify.

    Returns a summary dict with {qualified, ism_stage, threshold, outreacher_task_id}.
    Defensive — any per-step failure logs and continues; the overall researcher
    run must not crash on persistence issues.
    """
    from models.models import LeadRequirement, LeadRequirementUpsert, Lead, utc_now
    from services.requirement_service import upsert_lead_requirements
    from services.agent.agent_task_service import create_agent_task
    from sqlmodel import select

    scoring_result = scoring_result or {}
    signals = scoring_result.get("signals") or {}

    # Build a requirement upsert from whatever the scoring pipeline extracted.
    try:
        payload = LeadRequirementUpsert(
            lead_id=lead_id,
            use_case=_coerce_list(signals.get("use_case") or scoring_result.get("use_case")),
            budget_range=_coerce_list(signals.get("budget_range") or scoring_result.get("budget_range")),
            timeline=_coerce_list(signals.get("timeline") or scoring_result.get("timeline")),
            decision_maker=_coerce_list(signals.get("decision_maker") or scoring_result.get("decision_maker")),
            pain_points=_coerce_list(signals.get("pain_points") or scoring_result.get("pain_points")),
            required_products=_coerce_list(signals.get("required_products") or scoring_result.get("required_products")),
            notes="Auto-extracted by researcher agent",
            structured_data=scoring_result,
        )
        # Only write if at least one field has a value — avoid creating empty rows.
        non_empty = any([
            payload.use_case, payload.budget_range, payload.timeline,
            payload.decision_maker, payload.pain_points, payload.required_products,
        ])
        if non_empty:
            upsert_lead_requirements(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                data=payload,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ResearcherAgent] requirement upsert failed: %s", exc)

    threshold = _get_qualify_threshold(session, company_id)
    qualified = icp_score >= threshold

    # Fetch the Lead fresh so we can stamp state.  Never crash the whole run if
    # the lead was deleted between enqueue and execution.
    lead = session.exec(select(Lead).where(Lead.id == lead_id, Lead.company_id == company_id)).first()
    if lead is None:
        return {"qualified": qualified, "threshold": threshold, "skipped": "lead_not_found"}

    summary: dict = {"qualified": qualified, "threshold": threshold, "icp_score": icp_score}

    if qualified:
        try:
            task = create_agent_task(
                session=session,
                company_id=company_id,
                task_type="qualify_lead",
                assigned_agent="outreacher",
                input_json={"lead_id": lead_id, "stage": lead.ism_stage or "new"},
                lead_id=lead_id,
                idempotency_key=f"outreacher:{lead_id}:{lead.ism_stage or 'new'}",
                actor_user_id=actor_user_id,
            )
            summary["outreacher_task_id"] = task.id
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ResearcherAgent] outreacher enqueue failed: %s", exc)
            summary["outreacher_enqueue_error"] = str(exc)
    else:
        lead.qualification_status = "disqualified"
        lead.ism_stage = "closed_lost"
        lead.updated_at = utc_now()
        lead.updated_by = actor_user_id
        session.add(lead)
        session.commit()
        summary["ism_stage"] = lead.ism_stage

    return summary


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
    agent = await create_agent(llm, company_id)

    icp_score = 0.5
    scoring_result: dict = {}
    output_text = ""
    errors: list[str] = []

    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
        output_text = result["messages"][-1].content

        # Pull the scoring result + icp_score populated by researcher_node (if it ran
        # inside the agent's tool-call sequence).  Some agents emit these via state;
        # others don't — so fall back to a direct score_lead call below.
        state_bag = result.get("agent_results") or {}
        scoring_result = state_bag.get("researcher") or {}
        icp_score = float(result.get("icp_score") or 0.5)
    except Exception as exc:
        logger.warning("[ResearcherAgent] run failed: %s", exc)
        errors.append(str(exc))

    # Always run a direct scoring pass so qualification has a reliable score
    # even when the tool-calling agent skipped the researcher_node path.
    try:
        with Session(engine) as session:
            if not scoring_result:
                from services.leads.demand_generation_service import enrich_lead_if_needed, score_lead
                enrich_lead_if_needed(
                    session=session, company_id=company_id,
                    actor_user_id=actor_user_id, lead_id=lead_id,
                )
                scoring_result = score_lead(
                    session=session, company_id=company_id, lead_id=lead_id,
                ) or {}
                icp_score = float(scoring_result.get("score") or icp_score)

            qualification = _persist_signals_and_qualify(
                session=session,
                company_id=company_id,
                lead_id=lead_id,
                actor_user_id=actor_user_id,
                scoring_result=scoring_result,
                icp_score=icp_score,
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ResearcherAgent] qualification step failed: %s", exc)
        errors.append(f"qualification: {exc}")
        qualification = {"qualified": False, "error": str(exc)}

    return {
        "output": output_text,
        "errors": errors,
        "qualification": qualification,
        "icp_score": icp_score,
    }
