from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select

from credentials_service import get_company_setting_value, get_user_setting_value
from models.models import (
    CallTask,
    CompanySetting,
    Interaction,
    User,
    VoiceAgent,
    VoiceAgentExecutionEvent,
    VoiceAgentPromptVersion,
    VoiceAgentRuntimeConfig,
    utc_now,
)


DEFAULT_AGENT_NAME = "Default Rio"


@dataclass
class ResolvedVoiceAgentRuntime:
    agent: VoiceAgent
    runtime: VoiceAgentRuntimeConfig
    prompt_version: VoiceAgentPromptVersion
    system_prompt: str
    stt_provider: str
    llm_provider: str
    tts_provider: str
    telephony_engine: str | None
    ai_verbosity: str


def _setting(session: Session, company_id: int, key: str, fallback: str | None = None) -> str | None:
    return get_company_setting_value(session, company_id, key) or fallback


def ensure_default_voice_agent(
    session: Session,
    company_id: int,
    actor_user_id: int | None = None,
) -> VoiceAgent:
    existing = session.exec(
        select(VoiceAgent).where(
            VoiceAgent.company_id == company_id,
            VoiceAgent.is_default == True,  # noqa: E712
            VoiceAgent.archived_at.is_(None),
        )
    ).first()
    if existing:
        return existing

    agent = VoiceAgent(
        company_id=company_id,
        name=DEFAULT_AGENT_NAME,
        description="Default migrated voice agent.",
        is_default=True,
        status="active",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(agent)
    session.commit()
    session.refresh(agent)

    runtime = VoiceAgentRuntimeConfig(
        company_id=company_id,
        agent_id=agent.id,
        stt_provider=_setting(session, company_id, "STT_PROVIDER", "deepgram"),
        llm_provider=_setting(session, company_id, "LLM_PROVIDER", "mistral"),
        tts_provider=_setting(session, company_id, "TTS_PROVIDER", "cartesia"),
        telephony_engine=_setting(session, company_id, "TELEPHONY_ENGINE"),
        ai_verbosity=_setting(session, company_id, "AI_VERBOSITY", "2"),
        runtime_json={},
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(runtime)

    prompt = VoiceAgentPromptVersion(
        company_id=company_id,
        agent_id=agent.id,
        version=1,
        name="Migrated default prompt",
        system_prompt=_setting(
            session,
            company_id,
            "SYSTEM_PROMPT",
            "You are Rio, a concise inside-sales voice assistant.",
        ) or "You are Rio, a concise inside-sales voice assistant.",
        instructions=_setting(session, company_id, "SYSTEM_INSTRUCTION"),
        is_active=True,
        published_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(prompt)
    session.commit()
    session.refresh(agent)
    return agent


def get_agent_or_404(session: Session, company_id: int, agent_id: int) -> VoiceAgent:
    agent = session.exec(
        select(VoiceAgent).where(
            VoiceAgent.id == agent_id,
            VoiceAgent.company_id == company_id,
            VoiceAgent.archived_at.is_(None),
        )
    ).first()
    if not agent:
        raise HTTPException(status_code=404, detail="Voice agent not found")
    return agent


def get_runtime_config(session: Session, company_id: int, agent_id: int) -> VoiceAgentRuntimeConfig:
    runtime = session.exec(
        select(VoiceAgentRuntimeConfig).where(
            VoiceAgentRuntimeConfig.company_id == company_id,
            VoiceAgentRuntimeConfig.agent_id == agent_id,
        )
    ).first()
    if runtime:
        return runtime

    runtime = VoiceAgentRuntimeConfig(
        company_id=company_id,
        agent_id=agent_id,
        stt_provider=_setting(session, company_id, "STT_PROVIDER", "deepgram"),
        llm_provider=_setting(session, company_id, "LLM_PROVIDER", "mistral"),
        tts_provider=_setting(session, company_id, "TTS_PROVIDER", "cartesia"),
        telephony_engine=_setting(session, company_id, "TELEPHONY_ENGINE"),
        ai_verbosity=_setting(session, company_id, "AI_VERBOSITY", "2"),
        runtime_json={},
    )
    session.add(runtime)
    session.commit()
    session.refresh(runtime)
    return runtime


def get_active_prompt(session: Session, company_id: int, agent_id: int) -> VoiceAgentPromptVersion:
    prompt = session.exec(
        select(VoiceAgentPromptVersion).where(
            VoiceAgentPromptVersion.company_id == company_id,
            VoiceAgentPromptVersion.agent_id == agent_id,
            VoiceAgentPromptVersion.is_active == True,  # noqa: E712
        ).order_by(VoiceAgentPromptVersion.version.desc())
    ).first()
    if prompt:
        return prompt

    prompt = VoiceAgentPromptVersion(
        company_id=company_id,
        agent_id=agent_id,
        version=1,
        name="Default prompt",
        system_prompt=_setting(
            session,
            company_id,
            "SYSTEM_PROMPT",
            "You are Rio, a concise inside-sales voice assistant.",
        ) or "You are Rio, a concise inside-sales voice assistant.",
        is_active=True,
        published_at=utc_now(),
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def resolve_agent_for_call(
    session: Session,
    company_id: int,
    user: User | None = None,
    agent_id: int | None = None,
    interaction_id: int | None = None,
    call_task_id: int | None = None,
) -> ResolvedVoiceAgentRuntime:
    resolved_agent_id = agent_id

    if resolved_agent_id is None and call_task_id:
        task = session.get(CallTask, call_task_id)
        if task and task.company_id == company_id:
            resolved_agent_id = task.agent_id

    if resolved_agent_id is None and interaction_id:
        interaction = session.get(Interaction, interaction_id)
        if interaction and interaction.company_id == company_id:
            resolved_agent_id = interaction.agent_id
            metadata = interaction.metadata_json or {}
            if resolved_agent_id is None and metadata.get("agent_id"):
                try:
                    resolved_agent_id = int(metadata["agent_id"])
                except (TypeError, ValueError):
                    resolved_agent_id = None

    agent = (
        get_agent_or_404(session, company_id, resolved_agent_id)
        if resolved_agent_id
        else ensure_default_voice_agent(session, company_id, user.id if user else None)
    )
    runtime = get_runtime_config(session, company_id, agent.id)
    prompt = get_active_prompt(session, company_id, agent.id)

    if interaction_id:
        interaction = session.get(Interaction, interaction_id)
        if interaction and interaction.company_id == company_id and interaction.agent_id != agent.id:
            interaction.agent_id = agent.id
            interaction.metadata_json = {**(interaction.metadata_json or {}), "agent_id": agent.id}
            session.add(interaction)
            session.commit()

    system_prompt = prompt.system_prompt
    if prompt.instructions:
        system_prompt = f"{system_prompt}\n\n### AGENT INSTRUCTIONS\n{prompt.instructions}"

    # Company-wide instruction from "Voice & AI Engine" settings tab
    company_instruction = _setting(session, company_id, "SYSTEM_INSTRUCTION")
    if company_instruction:
        system_prompt = f"{system_prompt}\n\n### COMPANY INSTRUCTIONS\n{company_instruction}"

    # User personal persona — prepend so it sets tone regardless of which agent is active
    if user:
        user_prompt = get_user_setting_value(session, user.id, "SYSTEM_PROMPT")
        if user_prompt:
            system_prompt = f"{user_prompt}\n\n{system_prompt}"

    # Substitute {agent_name} and {company_name} placeholders throughout the prompt
    agent_name = _setting(session, company_id, "AGENT_NAME") or "Rio"
    from models.models import Company as _Company
    _company = session.get(_Company, company_id) if company_id else None
    company_name = (_company.name if _company else None) or "the company"
    system_prompt = (
        system_prompt
        .replace("{agent_name}", agent_name)
        .replace("{company_name}", company_name)
    )

    return ResolvedVoiceAgentRuntime(
        agent=agent,
        runtime=runtime,
        prompt_version=prompt,
        system_prompt=system_prompt,
        stt_provider=runtime.stt_provider or _setting(session, company_id, "STT_PROVIDER", "deepgram") or "deepgram",
        llm_provider=runtime.llm_provider or _setting(session, company_id, "LLM_PROVIDER", "mistral") or "mistral",
        tts_provider=runtime.tts_provider or _setting(session, company_id, "TTS_PROVIDER", "cartesia") or "cartesia",
        telephony_engine=runtime.telephony_engine or _setting(session, company_id, "TELEPHONY_ENGINE"),
        ai_verbosity=runtime.ai_verbosity or _setting(session, company_id, "AI_VERBOSITY", "2") or "2",
    )


def log_voice_agent_event(
    session: Session,
    company_id: int,
    event_type: str,
    agent_id: int | None = None,
    interaction_id: int | None = None,
    call_task_id: int | None = None,
    provider: str | None = None,
    summary: str | None = None,
    payload: dict | None = None,
    commit: bool = True,
) -> VoiceAgentExecutionEvent:
    event = VoiceAgentExecutionEvent(
        company_id=company_id,
        agent_id=agent_id,
        interaction_id=interaction_id,
        call_task_id=call_task_id,
        event_type=event_type,
        provider=provider,
        summary=summary,
        payload=payload or {},
    )
    session.add(event)
    if commit:
        session.commit()
        session.refresh(event)
    return event
