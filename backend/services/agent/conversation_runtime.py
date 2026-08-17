"""Transport-neutral agent conversation runtime.

Chat and browser voice sessions use this module for the text reasoning/tool
loop. Phone VoicePipeline remains responsible for audio-specific behavior.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, AsyncGenerator

from sqlmodel import Session, select

from credentials_service import get_company_credential, get_company_setting_value
from database import engine
from models.models import AgentChatMessage, AgentChatSession, User, utc_now
from services.ai.llm import get_llm_service
from services.voice_agent_runtime_service import resolve_agent_for_call
from tool_adapter import execute_mcp_tool, get_mistral_tools
from agents._format_utils import to_compact
from utils.lead_utils import get_comprehensive_lead_context

logger = logging.getLogger(__name__)


def _setting(session: Session, company_id: int, key: str, fallback: str | None = None) -> str | None:
    return get_company_setting_value(session, company_id, key) or fallback


def _tool_call_dict(call: Any) -> dict:
    if isinstance(call, dict):
        return call
    return {
        "id": getattr(call, "id", None) or f"call_{int(time.time() * 1000)}",
        "type": "function",
        "function": {
            "name": getattr(getattr(call, "function", None), "name", ""),
            "arguments": getattr(getattr(call, "function", None), "arguments", "{}") or "{}",
        },
    }


def _credential(session: Session, company_id: int, provider: str) -> str | None:
    p = provider.upper()
    return get_company_credential(session, company_id, f"{p}_LLM_API_KEY") or get_company_credential(
        session, company_id, f"{p}_API_KEY"
    ) or get_company_credential(session, company_id, "LLM_API_KEY")


def _model(session: Session, company_id: int, provider: str) -> str | None:
    p = provider.upper()
    return (
        _setting(session, company_id, f"{p}_LLM_MODEL")
        or _setting(session, company_id, f"{p}_MODEL")
        or _setting(session, company_id, "LLM_MODEL")
    )


def _load_session(session: Session, company_id: int, session_id: int) -> AgentChatSession:
    item = session.exec(
        select(AgentChatSession).where(
            AgentChatSession.id == session_id,
            AgentChatSession.company_id == company_id,
        )
    ).first()
    if not item:
        raise ValueError("Chat session not found")
    return item


async def stream_response(
    *,
    company_id: int,
    user_id: int | None,
    session_id: int,
    user_text: str,
) -> AsyncGenerator[dict[str, Any], None]:
    """Persist a user turn and stream assistant/tool events as JSON-safe dicts."""
    text = user_text.strip()
    if not text:
        raise ValueError("Message cannot be empty")

    with Session(engine) as db:
        chat = _load_session(db, company_id, session_id)
        if user_id and chat.user_id and chat.user_id != user_id:
            raise ValueError("Chat session belongs to another user")
        chat.updated_at = utc_now()
        db.add(AgentChatMessage(company_id=company_id, session_id=session_id, role="user", content=text))
        db.add(chat)
        db.commit()
        messages = db.exec(
            select(AgentChatMessage)
            .where(AgentChatMessage.session_id == session_id, AgentChatMessage.company_id == company_id)
            .order_by(AgentChatMessage.created_at.asc(), AgentChatMessage.id.asc())
        ).all()

        runtime = resolve_agent_for_call(db, company_id, user=db.get(User, user_id) if user_id else None, agent_id=chat.agent_id)
        system_prompt = runtime.system_prompt
        if chat.lead_id:
            try:
                lead_context = get_comprehensive_lead_context(db, chat.lead_id)
                if lead_context:
                    system_prompt += f"\n\n### LEAD CONTEXT\n{lead_context}"
            except Exception as exc:
                logger.warning("[ConversationRuntime] lead context unavailable: %s", exc)
        provider = runtime.llm_provider or "mistral"
        llm = get_llm_service(provider, system_prompt, api_key=_credential(db, company_id, provider), model=_model(db, company_id, provider))

        for item in messages:
            if item.role == "user":
                llm.add_user_message(item.content)
            elif item.role == "assistant":
                calls = item.metadata_json.get("tool_calls") if item.metadata_json else None
                llm.add_assistant_message(item.content, tool_calls=calls)
            elif item.role == "tool":
                llm.add_tool_message(item.tool_call_id or "unknown", item.tool_name or "tool", item.content)

        tools = get_mistral_tools(company_id, agent_id=chat.agent_id)
        accumulated = ""
        for _ in range(5):
            tool_calls = None
            full_reply = ""
            async for event in llm.stream(tools=tools):
                kind = event.get("type")
                if kind == "token":
                    accumulated += event.get("content", "")
                    yield {"type": "token", "content": event.get("content", "")}
                elif kind == "finished":
                    full_reply = event.get("full_reply", "") or ""
                    tool_calls = [_tool_call_dict(c) for c in (event.get("tool_calls") or [])]
                elif kind == "error":
                    yield {"type": "error", "content": event.get("content", "Agent error")}
                    return

            llm.add_assistant_message(full_reply, tool_calls=tool_calls or None)
            if full_reply:
                db.add(AgentChatMessage(
                    company_id=company_id, session_id=session_id, role="assistant", content=full_reply,
                    metadata_json={"tool_calls": tool_calls or [], "provider": provider},
                ))
                yield {"type": "message", "content": full_reply}

            if not tool_calls:
                break

            for call in tool_calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"].get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                yield {"type": "tool_start", "tool": name}
                result = await execute_mcp_tool(name, arguments, user_id=user_id, session=db)
                result_text = to_compact(result)
                db.add(AgentChatMessage(
                    company_id=company_id, session_id=session_id, role="tool", content=result_text,
                    tool_name=name, tool_call_id=call.get("id"), tool_arguments=arguments,
                    tool_result=result,
                ))
                llm.add_tool_message(call.get("id") or "unknown", name, result_text)
                yield {"type": "tool_result", "tool": name, "result": result}
            db.commit()

        chat.updated_at = utc_now()
        db.add(chat)
        db.commit()
        yield {"type": "done", "content": accumulated}


def create_session(session: Session, company_id: int, user_id: int, agent_id: int, lead_id: int | None, transport: str) -> AgentChatSession:
    item = AgentChatSession(
        company_id=company_id, user_id=user_id, agent_id=agent_id, lead_id=lead_id,
        transport=transport, created_by=user_id, updated_by=user_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item
