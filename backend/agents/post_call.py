from __future__ import annotations
import logging
from langchain_core.tools import tool
from utils.tracing import traceable_async

logger = logging.getLogger(__name__)


@tool
def save_call_summary(
    lead_id: int, company_id: int, actor_user_id: int,
    transcript: str, icp_score: float = 0.5, sentiment: str = "neutral",
    pain_points: list = None, questions_asked: list = None, bant_answers: dict = None,
) -> str:
    """Save a structured call summary to the CRM as an Interaction record.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the user who made the call.
        transcript: Full call transcript text.
        icp_score: Lead fit score (0.0-1.0).
        sentiment: Overall sentiment (positive/neutral/negative).
        pain_points: List of identified pain points.
        questions_asked: List of questions the lead asked.
        bant_answers: Dict with budget/authority/need/timeline keys.
    """
    try:
        from agents.post_call_nurture import CallSummarizer
        summary = CallSummarizer.summarize_call(
            lead_id=lead_id, transcript=transcript, icp_score=icp_score,
            sentiment=sentiment, pain_points=pain_points or [],
            questions_asked=questions_asked or [], bant_answers=bant_answers or {},
            company_id=company_id,
        )
        CallSummarizer.save_summary_to_crm(
            lead_id=lead_id, summary=summary,
            company_id=company_id, actor_user_id=actor_user_id,
        )
        return f"Call summary saved for lead {lead_id}."
    except Exception as exc:
        logger.warning("[PostCallAgent] save_call_summary failed: %s", exc)
        return f"Failed to save summary: {exc}"


@tool
def update_lead_status(lead_id: int, new_status: str, notes: str = "") -> str:
    """Update a lead's CRM status after a call.

    Args:
        lead_id: ID of the lead.
        new_status: New status (e.g. "Demo Scheduled", "Follow-up", "Not Qualified").
        notes: Optional notes to attach.
    """
    try:
        from agents.post_call_nurture import CRMUpdater
        CRMUpdater.update_lead_status(lead_id=lead_id, new_status=new_status, notes=notes)
        return f"Lead {lead_id} status updated to '{new_status}'."
    except Exception as exc:
        logger.warning("[PostCallAgent] update_lead_status failed: %s", exc)
        return f"Status update failed: {exc}"


@tool
def send_followup_email(
    lead_id: int, company_id: int, actor_user_id: int,
    lead_name: str, lead_email: str, pain_points: list = None,
    questions: list = None, icp_score: float = 0.5, suggested_action: str = "send_followup",
) -> str:
    """Send a personalized follow-up email to a lead after a call.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the sender.
        lead_name: Lead's display name.
        lead_email: Lead's email address.
        pain_points: Detected pain points to reference in the email.
        questions: Questions the lead asked during the call.
        icp_score: Lead fit score.
        suggested_action: Next step hint (send_followup/book_demo).
    """
    try:
        from database import engine
        from sqlmodel import Session
        from agents.post_call_nurture import EmailWriter
        with Session(engine) as session:
            EmailWriter.send_personalized_followup(
                session=session, company_id=company_id, actor_user_id=actor_user_id,
                lead_id=lead_id, lead_name=lead_name, lead_email=lead_email,
                company="", pain_points=pain_points or [], questions=questions or [],
                icp_score=icp_score, suggested_action=suggested_action,
            )
        return f"Follow-up email sent to {lead_email}."
    except Exception as exc:
        logger.warning("[PostCallAgent] send_followup_email failed: %s", exc)
        return f"Email send failed: {exc}"


POST_CALL_TOOLS = [save_call_summary, update_lead_status, send_followup_email]


_POST_CALL_SYSTEM_PROMPT = (
    "You are the Post-Call Agent for Rio CRM.\n"
    "After a sales call you MUST:\n"
    "1. Call save_call_summary with the full transcript, sentiment, pain points, BANT answers.\n"
    "2. Determine the right next action:\n"
    "   - ICP score > 0.75 AND positive outcome -> call update_lead_status with Demo Scheduled\n"
    "   - Outcome is not_qualified -> call update_lead_status with Not Qualified\n"
    "   - Otherwise -> call update_lead_status with Follow-up\n"
    "3. If a follow-up email is needed, call send_followup_email.\n\n"
    "Be thorough -- missed follow-ups lose deals."
)


async def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_async_checkpointer
    from services.mcp.connected_providers import agent_system_prompt
    return create_agent(
        llm,
        tools=POST_CALL_TOOLS,
        system_prompt=agent_system_prompt(_POST_CALL_SYSTEM_PROMPT, company_id),
        checkpointer=await get_async_checkpointer(),
    )


@traceable_async(name="run_post_call_agent", run_type="chain", tags=["post_call"])
async def run(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
    lead_name: str,
    lead_email: str,
    transcript: str,
    call_outcome: str,
    sentiment: str,
    icp_score: float,
    pain_points: list,
    questions_asked: list,
    bant_answers: dict,
    thread_id: str | None = None,
) -> dict:
    """Process a completed call: save summary, update CRM, send follow-up.

    Args:
        lead_id: ID of the lead.
        company_id: Tenant ID.
        actor_user_id: ID of the SDR who made the call.
        lead_name: Lead display name.
        lead_email: Lead email address.
        transcript: Full call transcript.
        call_outcome: positive / neutral / not_qualified.
        sentiment: positive / neutral / negative.
        icp_score: Lead ICP fit score (0.0-1.0).
        pain_points: Pain points detected in the transcript.
        questions_asked: Questions the lead raised.
        bant_answers: BANT dict with budget/authority/need/timeline.
        thread_id: LangGraph thread for checkpointed memory (optional).
    """
    from database import engine
    from sqlmodel import Session
    from langchain_core.messages import HumanMessage
    from agents.llm_factory import get_agent_llm
    query = (
        f"Process post-call for lead {lead_id} ({lead_name}, {lead_email}). "
        f"Outcome={call_outcome}, sentiment={sentiment}, icp_score={icp_score:.2f}. "
        f"Pain points: {'|'.join(pain_points) if isinstance(pain_points, list) else pain_points}. "
        f"BANT: {'|'.join(f'{k}={v}' for k, v in bant_answers.items()) if isinstance(bant_answers, dict) else bant_answers}. "
        f"Save summary, update CRM status, send follow-up if appropriate. "
        f"transcript_length={len(transcript)}."
    )
    config = {"configurable": {"thread_id": thread_id or f"post_call_{company_id}_{lead_id}"}}
    with Session(engine) as session:
        llm = get_agent_llm(session, company_id)
    agent = await create_agent(llm, company_id)
    try:
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=query)]},
            config=config,
        )
        output = result["messages"][-1].content
    except Exception as exc:
        logger.warning("[PostCallAgent] run failed: %s", exc)
        return {"output": "", "errors": [str(exc)]}

    # Fire-and-forget: eval the call using real transcript data
    _schedule_call_eval(company_id, lead_id)

    return {"output": output, "errors": []}


def _schedule_call_eval(company_id: int, lead_id: int) -> None:
    """Background eval: find the latest interaction for this lead and judge it."""
    import asyncio

    async def _run() -> None:
        try:
            from database import engine
            from sqlmodel import Session, select
            from models.models import Interaction
            from services.evals.call_eval_service import run_call_eval
            with Session(engine) as s:
                interaction = s.exec(
                    select(Interaction)
                    .where(
                        Interaction.lead_id == lead_id,
                        Interaction.company_id == company_id,
                        Interaction.type == "call",
                        Interaction.transcript.is_not(None),
                    )
                    .order_by(Interaction.created_at.desc())
                    .limit(1)
                ).first()
                if interaction:
                    await run_call_eval(s, interaction.id, company_id)
        except Exception as exc:
            logger.warning("[PostCallAgent] background eval failed: %s", exc)

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_run())
        else:
            loop.run_until_complete(_run())
    except Exception as exc:
        logger.warning("[PostCallAgent] could not schedule eval: %s", exc)
