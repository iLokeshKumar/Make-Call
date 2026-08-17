from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

from utils.tracing import traceable_async

logger = logging.getLogger(__name__)


@tool
def draft_proposal(
    lead_id: int,
    company_id: int,
    actor_user_id: int,
    request_text: str = "",
    interaction_id: int | None = None,
    source_channel: str = "",
) -> str:
    """Create a validated proposal/RFP/RFQ draft for a lead."""
    try:
        from database import engine
        from sqlmodel import Session
        from services.proposal.proposal_service import create_proposal_draft

        with Session(engine) as session:
            result = create_proposal_draft(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
                interaction_id=interaction_id,
                request_text=request_text or None,
                source_channel=source_channel or None,
            )
        return str({
            "proposal_id": result["id"],
            "quote_id": result.get("quote_id"),
            "status": result["status"],
            "validation": result["validation"],
            "tabular_scores": result.get("tabular_scores"),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProposalAgent] draft_proposal failed: %s", exc)
        return f"Proposal draft failed: {exc}"


@tool
def send_proposal_for_approval(
    proposal_id: int,
    company_id: int,
    actor_user_id: int,
    channels: list[str],
    subject: str = "",
    message: str = "",
) -> str:
    """Queue a proposal send task. Approval is applied by the AgentTask policy."""
    try:
        from database import engine
        from sqlmodel import Session
        from services.proposal.proposal_service import enqueue_proposal_send

        with Session(engine) as session:
            task = enqueue_proposal_send(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                proposal_id=proposal_id,
                channels=channels,
                subject=subject or None,
                message=message or None,
            )
        return f"Proposal send task {task.id} queued with status={task.status}."
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ProposalAgent] send_proposal_for_approval failed: %s", exc)
        return f"Proposal send failed: {exc}"


PROPOSAL_TOOLS = [draft_proposal, send_proposal_for_approval]

_PROPOSAL_SYSTEM_PROMPT = (
    "You are Rio's Proposal Agent for RFP/RFQ and quote creation.\n"
    "You convert buyer intent into validated requirements, solution design, pricing draft, "
    "proposal document sections, and an approval-gated send task.\n\n"
    "Rules:\n"
    "- Draft before sending.\n"
    "- Do not send blocked proposals.\n"
    "- Treat pricing, stock, product specs, and discounts as data-backed facts only.\n"
    "- If requirement fields are missing, keep the proposal in review and surface the missing fields."
)


async def create_agent(llm, company_id: int = 0):
    from langchain.agents import create_agent
    from agents.checkpointer import get_async_checkpointer

    return create_agent(
        llm,
        tools=PROPOSAL_TOOLS,
        system_prompt=_PROPOSAL_SYSTEM_PROMPT,
        checkpointer=await get_async_checkpointer(),
    )


@traceable_async(name="run_proposal_agent", run_type="chain", tags=["proposal"])
async def run(
    *,
    company_id: int,
    actor_user_id: int = 0,
    lead_id: int | None = None,
    query: str = "",
    request_text: str = "",
    interaction_id: int | None = None,
    source_channel: str = "",
    proposal_id: int | None = None,
    channels: list[str] | None = None,
    **_unused: Any,
) -> dict:
    """Worker-friendly entry point for proposal tasks."""
    if proposal_id and channels:
        output = send_proposal_for_approval.invoke({
            "proposal_id": proposal_id,
            "company_id": company_id,
            "actor_user_id": actor_user_id,
            "channels": channels,
            "subject": "",
            "message": "",
        })
        return {"output": output, "errors": []}

    if not lead_id:
        return {"output": "", "errors": ["proposal agent requires lead_id"]}

    output = draft_proposal.invoke({
        "lead_id": lead_id,
        "company_id": company_id,
        "actor_user_id": actor_user_id,
        "request_text": request_text or query,
        "interaction_id": interaction_id,
        "source_channel": source_channel,
    })
    return {"output": output, "errors": []}

