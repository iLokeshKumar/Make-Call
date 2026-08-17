"""
Agent API routes — exposes the multi-agent orchestrator over HTTP.

Endpoints:
  POST /crm/agents/ask              - Freeform question routed by supervisor
  POST /crm/agents/run/{agent_name} - Run a specific agent directly
  POST /crm/agents/pre-call         - Pre-call enrichment workflow
  POST /crm/agents/post-call        - Post-call CRM update workflow
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth import get_current_user
from models.models import User

router = APIRouter(prefix="/crm/agents", tags=["agents"])


# Request / Response models

class AskRequest(BaseModel):
    query: str
    lead_id: Optional[int] = None
    thread_id: Optional[str] = None


class RunAgentRequest(BaseModel):
    query: str
    lead_id: Optional[int] = None
    thread_id: Optional[str] = None
    extra: Dict[str, Any] = {}


class PreCallRequest(BaseModel):
    lead_id: int


class PostCallRequest(BaseModel):
    lead_id: int
    lead_name: str = ""
    lead_email: str = ""
    call_transcript: str = ""
    call_duration: int = 0
    call_outcome: str = "neutral"
    sentiment: str = "neutral"
    icp_score: float = 0.5
    pain_points: List[str] = []
    questions_asked: List[str] = []
    bant_answers: Dict[str, Any] = {}


class AgentResponse(BaseModel):
    output: str = ""
    agents_run: List[str] = []
    errors: List[str] = []


# Endpoints

@router.post("/ask", response_model=AgentResponse)
async def ask_agent(
    body: AskRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Ask Rio a freeform question. The supervisor automatically routes to the
    right agent(s) based on the query content.

    Examples:
    - "What are the best objection rebuttals for pricing?"
    - "How many leads are in negotiation?"
    - "Enroll lead 42 in the Q1 outreach campaign"
    """
    try:
        from agents.orchestrator import ask
        result = await ask(
            query=body.query,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            lead_id=body.lead_id,
            thread_id=body.thread_id,
        )
        return AgentResponse(**result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/run/{agent_name}", response_model=AgentResponse)
async def run_named_agent(
    agent_name: str,
    body: RunAgentRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run a specific agent by name with a natural-language query.

    Valid agent names: knowledge, enrichment, researcher, post_call,
    coach, ism, campaign, quote, analytics.
    """
    valid = ["knowledge", "enrichment", "researcher", "post_call",
             "coach", "ism", "campaign", "quote", "analytics"]
    if agent_name not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown agent '{agent_name}'. Valid: {valid}",
        )
    try:
        from agents.orchestrator import run_agent
        kwargs = dict(body.extra)
        if body.lead_id is not None:
            kwargs.setdefault("lead_id", body.lead_id)
        result = await run_agent(
            agent_name=agent_name,
            query=body.query,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            thread_id=body.thread_id,
            **kwargs,
        )
        return AgentResponse(
            output=result.get("output", ""),
            errors=result.get("errors", []),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/pre-call")
async def pre_call_workflow(
    body: PreCallRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run the pre-call enrichment workflow for a lead.

    Returns: icp_score, lead_data, kb_context, interaction_history
    """
    try:
        from agents.orchestrator import run_pre_call
        result = await run_pre_call(
            lead_id=body.lead_id,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/post-call")
async def post_call_workflow(
    body: PostCallRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Run the post-call CRM update workflow.

    Saves call summary, updates lead status, sends follow-up email,
    and advances the ISM stage.
    """
    try:
        from agents.orchestrator import run_post_call
        result = await run_post_call(
            lead_id=body.lead_id,
            company_id=current_user.company_id,
            actor_user_id=current_user.id,
            lead_name=body.lead_name,
            lead_email=body.lead_email,
            call_transcript=body.call_transcript,
            call_duration=body.call_duration,
            call_outcome=body.call_outcome,
            sentiment=body.sentiment,
            icp_score=body.icp_score,
            pain_points=body.pain_points,
            questions_asked=body.questions_asked,
            bant_answers=body.bant_answers,
        )
        return result
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
