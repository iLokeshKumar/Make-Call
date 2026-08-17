from __future__ import annotations

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from auth import PermissionChecker, create_access_token
from database import get_session
from models.models import AgentChatMessage, AgentChatSession, User, VoiceAgent
from services.agent.conversation_runtime import create_session, stream_response

router = APIRouter(prefix="/crm/agent-chat", tags=["Agent Chat"])


class SessionCreate(BaseModel):
    agent_id: int
    lead_id: int | None = None
    transport: str = Field(default="chat", pattern="^(chat|web_call)$")


class MessageCreate(BaseModel):
    message: str = Field(min_length=1, max_length=20000)


def _agent(session: Session, user: User, agent_id: int) -> VoiceAgent:
    agent = session.exec(select(VoiceAgent).where(
        VoiceAgent.id == agent_id,
        VoiceAgent.company_id == user.company_id,
        VoiceAgent.archived_at.is_(None),
    )).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/sessions")
async def create_agent_session(
    body: SessionCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    agent = _agent(session, current_user, body.agent_id)
    item = create_session(session, current_user.company_id, current_user.id, agent.id, body.lead_id, body.transport)
    token = create_access_token(
        {"user_id": current_user.id, "company_id": current_user.company_id, "token_version": current_user.token_version, "typ": "web_call", "session_id": item.id, "agent_id": agent.id, "lead_id": body.lead_id},
        expires_delta=timedelta(minutes=10),
    ) if body.transport == "web_call" else None
    return {"session_id": item.id, "agent_id": agent.id, "transport": item.transport, "token": token}


@router.get("/sessions/{session_id}")
async def get_agent_session(
    session_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    item = session.exec(select(AgentChatSession).where(
        AgentChatSession.id == session_id,
        AgentChatSession.company_id == current_user.company_id,
    )).first()
    if not item:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = session.exec(select(AgentChatMessage).where(
        AgentChatMessage.session_id == session_id,
        AgentChatMessage.company_id == current_user.company_id,
    ).order_by(AgentChatMessage.created_at.asc(), AgentChatMessage.id.asc())).all()
    return {"session": item, "messages": messages}


@router.post("/sessions/{session_id}/messages")
async def send_message(
    session_id: int,
    body: MessageCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    async def events():
        async for event in stream_response(
            company_id=current_user.company_id, user_id=current_user.id,
            session_id=session_id, user_text=body.message,
        ):
            yield f"data: {json.dumps(event, default=str)}\n\n"
    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
