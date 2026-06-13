from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import (
    CallEvalResult,
    Interaction,
    User,
    VoiceAgent,
    VoiceAgentCreate,
    VoiceAgentExecutionEvent,
    VoiceAgentExecutionEventCreate,
    VoiceAgentExtractionResult,
    VoiceAgentExtractionTemplate,
    VoiceAgentExtractionTemplateUpsert,
    VoiceAgentGraph,
    VoiceAgentGraphUpdate,
    VoiceAgentPromptCreate,
    VoiceAgentPromptVersion,
    VoiceAgentRuntimeConfig,
    VoiceAgentRuntimeUpdate,
    VoiceAgentTool,
    VoiceAgentToolUpsert,
    VoiceAgentUpdate,
    utc_now,
)
from services.voice_agent_runtime_service import (
    ensure_default_voice_agent,
    get_active_prompt,
    get_agent_or_404,
    get_runtime_config,
    log_voice_agent_event,
)

router = APIRouter(prefix="/crm/voice-agents", tags=["Voice Agents"])


def _agent_payload(session: Session, company_id: int, agent: VoiceAgent) -> dict:
    runtime = get_runtime_config(session, company_id, agent.id)
    prompt = get_active_prompt(session, company_id, agent.id)
    return {
        "agent": agent,
        "runtime": runtime,
        "active_prompt": prompt,
    }


@router.get("")
async def list_voice_agents(
    include_archived: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    ensure_default_voice_agent(session, current_user.company_id, current_user.id)
    query = select(VoiceAgent).where(VoiceAgent.company_id == current_user.company_id)
    if not include_archived:
        query = query.where(VoiceAgent.archived_at.is_(None))
    agents = session.exec(query.order_by(VoiceAgent.is_default.desc(), VoiceAgent.name.asc())).all()
    return [_agent_payload(session, current_user.company_id, agent) for agent in agents]


@router.post("")
async def create_voice_agent(
    data: VoiceAgentCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    ensure_default_voice_agent(session, current_user.company_id, current_user.id)
    agent = VoiceAgent(
        company_id=current_user.company_id,
        name=data.name.strip(),
        description=data.description,
        is_default=False,
        status="active",
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    if not agent.name:
        raise HTTPException(status_code=400, detail="Agent name is required")
    session.add(agent)
    session.commit()
    session.refresh(agent)

    runtime = VoiceAgentRuntimeConfig(
        company_id=current_user.company_id,
        agent_id=agent.id,
        stt_provider=data.stt_provider,
        llm_provider=data.llm_provider,
        tts_provider=data.tts_provider,
        telephony_engine=data.telephony_engine,
        runtime_json={},
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(runtime)
    prompt = VoiceAgentPromptVersion(
        company_id=current_user.company_id,
        agent_id=agent.id,
        version=1,
        name="Initial prompt",
        system_prompt=data.system_prompt or "You are Rio, a concise inside-sales voice assistant.",
        is_active=True,
        published_at=utc_now(),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(prompt)
    session.commit()
    return _agent_payload(session, current_user.company_id, agent)


@router.get("/{agent_id}")
async def get_voice_agent(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    agent = get_agent_or_404(session, current_user.company_id, agent_id)
    return _agent_payload(session, current_user.company_id, agent)


@router.patch("/{agent_id}")
async def update_voice_agent(
    agent_id: int,
    data: VoiceAgentUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    agent = get_agent_or_404(session, current_user.company_id, agent_id)
    updates = data.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "name" and isinstance(value, str):
            value = value.strip()
            if not value:
                raise HTTPException(status_code=400, detail="Agent name is required")
        setattr(agent, key, value)
    agent.updated_at = utc_now()
    agent.updated_by = current_user.id
    session.add(agent)
    session.commit()
    return _agent_payload(session, current_user.company_id, agent)


@router.delete("/{agent_id}")
async def archive_voice_agent(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    agent = get_agent_or_404(session, current_user.company_id, agent_id)
    if agent.is_default:
        raise HTTPException(status_code=400, detail="Default voice agent cannot be archived")
    agent.status = "archived"
    agent.archived_at = utc_now()
    agent.updated_at = utc_now()
    agent.updated_by = current_user.id
    session.add(agent)
    session.commit()
    return {"status": "archived", "agent_id": agent.id}


@router.post("/{agent_id}/set-default")
async def set_default_voice_agent(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    agent = get_agent_or_404(session, current_user.company_id, agent_id)
    agents = session.exec(select(VoiceAgent).where(VoiceAgent.company_id == current_user.company_id)).all()
    for item in agents:
        item.is_default = item.id == agent.id
        item.updated_at = utc_now()
        item.updated_by = current_user.id
        session.add(item)
    session.commit()
    return {"status": "default_set", "agent_id": agent.id}


@router.get("/{agent_id}/runtime")
async def get_runtime(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    return get_runtime_config(session, current_user.company_id, agent_id)


@router.patch("/{agent_id}/runtime")
async def update_runtime(
    agent_id: int,
    data: VoiceAgentRuntimeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    runtime = get_runtime_config(session, current_user.company_id, agent_id)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(runtime, key, value)
    runtime.updated_at = utc_now()
    runtime.updated_by = current_user.id
    session.add(runtime)
    session.commit()
    session.refresh(runtime)
    return runtime


@router.get("/{agent_id}/prompts")
async def list_prompts(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    return session.exec(
        select(VoiceAgentPromptVersion)
        .where(
            VoiceAgentPromptVersion.company_id == current_user.company_id,
            VoiceAgentPromptVersion.agent_id == agent_id,
        )
        .order_by(VoiceAgentPromptVersion.version.desc())
    ).all()


@router.post("/{agent_id}/prompts")
async def create_prompt(
    agent_id: int,
    data: VoiceAgentPromptCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    last = session.exec(
        select(VoiceAgentPromptVersion)
        .where(
            VoiceAgentPromptVersion.company_id == current_user.company_id,
            VoiceAgentPromptVersion.agent_id == agent_id,
        )
        .order_by(VoiceAgentPromptVersion.version.desc())
    ).first()
    if data.publish:
        active = session.exec(
            select(VoiceAgentPromptVersion).where(
                VoiceAgentPromptVersion.company_id == current_user.company_id,
                VoiceAgentPromptVersion.agent_id == agent_id,
                VoiceAgentPromptVersion.is_active == True,  # noqa: E712
            )
        ).all()
        for item in active:
            item.is_active = False
            session.add(item)
    prompt = VoiceAgentPromptVersion(
        company_id=current_user.company_id,
        agent_id=agent_id,
        version=(last.version + 1) if last else 1,
        name=data.name,
        system_prompt=data.system_prompt,
        instructions=data.instructions,
        is_active=data.publish,
        traffic_split=data.traffic_split or 0,
        published_at=utc_now() if data.publish else None,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


@router.get("/{agent_id}/executions")
async def list_execution_events(
    agent_id: int,
    interaction_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    query = select(VoiceAgentExecutionEvent).where(
        VoiceAgentExecutionEvent.company_id == current_user.company_id,
        VoiceAgentExecutionEvent.agent_id == agent_id,
    )
    if interaction_id:
        query = query.where(VoiceAgentExecutionEvent.interaction_id == interaction_id)
    return session.exec(query.order_by(VoiceAgentExecutionEvent.created_at.desc()).limit(limit)).all()


@router.get("/{agent_id}/stats")
async def get_agent_stats(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    """Total call count and last call timestamp for an agent."""
    get_agent_or_404(session, current_user.company_id, agent_id)
    row = session.exec(
        select(
            func.count(VoiceAgentExecutionEvent.id).label("total_calls"),
            func.max(VoiceAgentExecutionEvent.created_at).label("last_call"),
        ).where(
            VoiceAgentExecutionEvent.company_id == current_user.company_id,
            VoiceAgentExecutionEvent.agent_id == agent_id,
            VoiceAgentExecutionEvent.event_type == "call_started",
        )
    ).one()
    return {"total_calls": row.total_calls or 0, "last_call": row.last_call}


@router.post("/events")
async def create_execution_event(
    data: VoiceAgentExecutionEventCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    if data.agent_id:
        get_agent_or_404(session, current_user.company_id, data.agent_id)
    return log_voice_agent_event(
        session=session,
        company_id=current_user.company_id,
        event_type=data.event_type,
        agent_id=data.agent_id,
        interaction_id=data.interaction_id,
        call_task_id=data.call_task_id,
        provider=data.provider,
        summary=data.summary,
        payload=data.payload,
    )


@router.get("/{agent_id}/extraction-templates")
async def list_extraction_templates(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    return session.exec(
        select(VoiceAgentExtractionTemplate).where(
            VoiceAgentExtractionTemplate.company_id == current_user.company_id,
            VoiceAgentExtractionTemplate.agent_id == agent_id,
        )
    ).all()


@router.post("/{agent_id}/extraction-templates")
async def create_extraction_template(
    agent_id: int,
    data: VoiceAgentExtractionTemplateUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    item = VoiceAgentExtractionTemplate(
        company_id=current_user.company_id,
        agent_id=agent_id,
        **data.model_dump(),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.get("/{agent_id}/tools")
async def list_tools(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    return session.exec(
        select(VoiceAgentTool).where(
            VoiceAgentTool.company_id == current_user.company_id,
            (VoiceAgentTool.agent_id == agent_id) | (VoiceAgentTool.agent_id.is_(None)),
        )
    ).all()


@router.post("/{agent_id}/tools")
async def create_tool(
    agent_id: int,
    data: VoiceAgentToolUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    item = VoiceAgentTool(
        company_id=current_user.company_id,
        agent_id=agent_id,
        **data.model_dump(),
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


@router.delete("/{agent_id}/tools/{tool_id}")
async def delete_tool(
    agent_id: int,
    tool_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    tool = session.exec(
        select(VoiceAgentTool).where(
            VoiceAgentTool.id == tool_id,
            VoiceAgentTool.company_id == current_user.company_id,
            VoiceAgentTool.agent_id == agent_id,
        )
    ).first()
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    session.delete(tool)
    session.commit()
    return {"status": "deleted", "tool_id": tool_id}


@router.get("/{agent_id}/graph")
async def get_graph(
    agent_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    get_agent_or_404(session, current_user.company_id, agent_id)
    graph = session.exec(
        select(VoiceAgentGraph).where(
            VoiceAgentGraph.company_id == current_user.company_id,
            VoiceAgentGraph.agent_id == agent_id,
        )
    ).first()
    if graph:
        return graph
    graph = VoiceAgentGraph(company_id=current_user.company_id, agent_id=agent_id, graph_json={}, is_enabled=False)
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph


@router.get("/{agent_id}/eval-stats")
async def get_eval_stats(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    """Aggregate eval quality stats for an agent's recent calls."""
    get_agent_or_404(session, current_user.company_id, agent_id)
    # Get recent interaction IDs linked to this agent via execution events
    events = session.exec(
        select(VoiceAgentExecutionEvent.interaction_id)
        .where(
            VoiceAgentExecutionEvent.company_id == current_user.company_id,
            VoiceAgentExecutionEvent.agent_id == agent_id,
            VoiceAgentExecutionEvent.interaction_id.is_not(None),
        )
        .distinct()
        .limit(limit)
    ).all()
    interaction_ids = [e for e in events if e]
    if not interaction_ids:
        return {"total": 0, "evaluated": 0, "pass_rate": None, "avg_overall": None, "axis_averages": {}}

    evals = session.exec(
        select(CallEvalResult).where(
            CallEvalResult.interaction_id.in_(interaction_ids),
            CallEvalResult.company_id == current_user.company_id,
        )
    ).all()
    if not evals:
        return {"total": len(interaction_ids), "evaluated": 0, "pass_rate": None, "avg_overall": None, "axis_averages": {}}

    passed = sum(1 for e in evals if e.passed)
    axes = ("call_summary", "lead_qualification", "next_action", "tool_use_honesty", "tone_brand", "handoff_escalation")
    axis_avgs: dict[str, float | None] = {}
    for ax in axes:
        scores = [getattr(e, f"score_{ax}") for e in evals if getattr(e, f"score_{ax}") is not None]
        axis_avgs[ax] = round(sum(scores) / len(scores), 2) if scores else None
    overall_scores = [e.score_overall for e in evals if e.score_overall is not None]
    return {
        "total": len(interaction_ids),
        "evaluated": len(evals),
        "pass_rate": round(passed / len(evals), 3) if evals else None,
        "avg_overall": round(sum(overall_scores) / len(overall_scores), 2) if overall_scores else None,
        "axis_averages": axis_avgs,
    }


@router.get("/{agent_id}/extraction-results")
async def list_extraction_results(
    agent_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    """Recent extraction results for an agent with template name."""
    get_agent_or_404(session, current_user.company_id, agent_id)
    results = session.exec(
        select(VoiceAgentExtractionResult)
        .where(
            VoiceAgentExtractionResult.company_id == current_user.company_id,
            VoiceAgentExtractionResult.agent_id == agent_id,
        )
        .order_by(VoiceAgentExtractionResult.created_at.desc())
        .limit(limit)
    ).all()
    templates = {
        t.id: t.name
        for t in session.exec(
            select(VoiceAgentExtractionTemplate).where(
                VoiceAgentExtractionTemplate.agent_id == agent_id,
                VoiceAgentExtractionTemplate.company_id == current_user.company_id,
            )
        ).all()
    }
    return [
        {
            "id": r.id,
            "template_id": r.template_id,
            "template_name": templates.get(r.template_id, "Unknown"),
            "interaction_id": r.interaction_id,
            "output_json": r.output_json,
            "status": r.status,
            "error": r.error,
            "created_at": r.created_at,
        }
        for r in results
    ]


@router.patch("/{agent_id}/prompts/{prompt_id}/traffic-split")
async def update_prompt_traffic_split(
    agent_id: int,
    prompt_id: int,
    traffic_split: int = Query(ge=0, le=100),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    """Set A/B traffic split percentage for a prompt version (0=inactive, 100=all traffic)."""
    get_agent_or_404(session, current_user.company_id, agent_id)
    prompt = session.exec(
        select(VoiceAgentPromptVersion).where(
            VoiceAgentPromptVersion.id == prompt_id,
            VoiceAgentPromptVersion.agent_id == agent_id,
            VoiceAgentPromptVersion.company_id == current_user.company_id,
        )
    ).first()
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt version not found")
    prompt.traffic_split = traffic_split
    prompt.updated_at = utc_now()
    prompt.updated_by = current_user.id
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


@router.patch("/{agent_id}/graph")
async def update_graph(
    agent_id: int,
    data: VoiceAgentGraphUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    graph = await get_graph(agent_id, session, current_user)
    graph.graph_json = data.graph_json
    graph.is_enabled = data.is_enabled
    graph.validation_json = {"valid": isinstance(data.graph_json, dict), "checked_at": utc_now().isoformat()}
    graph.updated_at = utc_now()
    graph.updated_by = current_user.id
    session.add(graph)
    session.commit()
    session.refresh(graph)
    return graph
