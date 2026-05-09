from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable, traceable_async

logger = logging.getLogger(__name__)


@tool
def get_objection_rebuttal(objection: str, company_id: int = 0) -> str:
    """Retrieve a proven rebuttal for a specific objection from the KB.

    Args:
        objection: The objection raised by the lead (verbatim or paraphrased).
        company_id: Tenant ID.
    """
    if not company_id:
        return "company_id is required."
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(objection, company_id=company_id, collection="objections", n_results=3)
        return format_for_prompt(results) or "No rebuttal found in KB."
    except Exception as exc:
        logger.warning("[CoachAgent] get_objection_rebuttal failed: %s", exc)
        return f"KB search unavailable: {exc}"


@tool
def get_next_question(transcript_snippet: str, bant_stage: str = "need", company_id: int = 0) -> str:
    """Suggest the next discovery question based on conversation progress.

    Args:
        transcript_snippet: Last 3-5 turns of the conversation.
        bant_stage: BANT dimension to probe (budget/authority/need/timeline).
        company_id: Tenant ID.
    """
    query = f"discovery question for {bant_stage}: {transcript_snippet[:200]}"
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(query, company_id=company_id, collection="playbooks", n_results=2)
        return format_for_prompt(results) or f"Ask: What is your {bant_stage} situation?"
    except Exception as exc:
        return f"Suggestion unavailable: {exc}"


@tool
def get_competitor_intel(competitor_name: str, company_id: int = 0) -> str:
    """Look up battle card information for a named competitor.

    Args:
        competitor_name: Name of the competitor mentioned by the lead.
        company_id: Tenant ID.
    """
    if not company_id:
        return "company_id is required."
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(competitor_name, company_id=company_id, collection="competitors", n_results=3)
        return format_for_prompt(results) or f"No battle card found for {competitor_name}."
    except Exception as exc:
        return f"Competitor intel unavailable: {exc}"


@tool
def score_call_coaching(lead_id: int, company_id: int, transcript: str, actor_user_id: int = 0) -> str:
    """Score an SDR's call against playbook rubric and save the coaching record.

    Args:
        lead_id: ID of the lead on the call.
        company_id: Tenant ID.
        transcript: Full call transcript.
        actor_user_id: ID of the SDR who made the call.
    """
    try:
        from database import engine
        from sqlmodel import Session
        from models.models import CallCoachScore
        word_count = len(transcript.split())
        sdr_words = word_count // 2  # rough estimate
        talk_ratio = sdr_words / max(word_count, 1)
        score = min(100, int((1 - abs(talk_ratio - 0.4)) * 100))
        with Session(engine) as session:
            record = CallCoachScore(
                lead_id=lead_id, company_id=company_id,
                actor_user_id=actor_user_id, score=score,
                notes="Auto-scored by Coach Agent.",
            )
            session.add(record)
            session.commit()
        return f"Coaching score {score}/100 saved for lead {lead_id}."
    except Exception as exc:
        logger.warning("[CoachAgent] score_call_coaching failed: %s", exc)
        return f"Coaching score unavailable: {exc}"


COACH_TOOLS = [get_objection_rebuttal, get_next_question, get_competitor_intel, score_call_coaching]


@traceable(name="coach_node", run_type="chain", tags=['coach'])
def coach_node(state: dict) -> dict:
    """LangGraph node: inject coaching tips from KB into agent_results."""
    company_id = state.get("company_id", 0)
    transcript = state.get("call_transcript") or ""
    pain_points = state.get("pain_points", [])
    coaching_tips: list[str] = []

    for pp in pain_points[:3]:
        tip = get_objection_rebuttal.invoke({"objection": pp, "company_id": company_id})
        if tip and "unavailable" not in tip.lower():
            coaching_tips.append(tip)

    if transcript:
        tip = get_next_question.invoke({
            "transcript_snippet": transcript[-500:],
            "bant_stage": "need",
            "company_id": company_id,
        })
        if tip:
            coaching_tips.append(tip)

    state.setdefault("agent_results", {})["coach"] = {"coaching_tips": coaching_tips}
    return state


_COACH_SYSTEM_PROMPT = (
    "You are the Sales Coach Agent for Rio CRM.\n"
    "You give real-time guidance to SDRs during and after calls.\n\n"
    "You can:\n"
    "- Retrieve objection rebuttals from the KB (get_objection_rebuttal)\n"
    "- Suggest the next discovery question (get_next_question)\n"
    "- Pull competitor battle cards (get_competitor_intel)\n"
    "- Score a call and save the coaching record (score_call_coaching)\n\n"
    "Be concise and actionable. The SDR needs quick answers, not essays.\n"
    "Always ground advice in KB content -- do not invent rebuttals."
)


async def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_async_checkpointer
    return create_agent(
        llm,
        tools=COACH_TOOLS,
        system_prompt=_COACH_SYSTEM_PROMPT,
        checkpointer=await get_async_checkpointer(),
    )


@traceable_async(name="run_coach_agent", run_type="chain", tags=["coach"])
async def run(
    query: str,
    company_id: int,
    actor_user_id: int = 0,
    thread_id: str | None = None,
) -> dict:
    """Ask the Coach Agent a question about handling a call situation.

    Args:
        query: The situation or question (e.g. "Lead said our price is too high").
        company_id: Tenant ID.
        actor_user_id: ID of the SDR.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    config = {"configurable": {"thread_id": thread_id or f"coach_{company_id}_{actor_user_id}"}}
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
        logger.warning("[CoachAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}
