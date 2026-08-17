from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlmodel import Session

from auth import get_current_user
from credentials_service import get_company_setting_value
from database import engine, get_session
from models.models import CallEvalResult, User
from services.evals.llm_judge import (
    JUDGE_AXES,
    PROVIDER_DEFAULTS,
    CallJudge,
    EvalCase,
    build_judge_from_settings,
    summarize_results,
)


router = APIRouter(prefix="/evals", tags=["Evals"])


# ---------------------------------------------------------------------------
# Legacy batch judge (kept for manual/CI eval runs)
# ---------------------------------------------------------------------------

class EvalCaseRequest(BaseModel):
    id: str | None = None
    task: str = Field(..., min_length=1)
    model_output: str = Field(..., min_length=1)
    reference: str = ""
    rubric: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalRunRequest(BaseModel):
    cases: list[EvalCaseRequest] = Field(..., min_length=1, max_length=50)
    model: str | None = None
    provider: str | None = None
    concurrency: int = Field(default=5, ge=1, le=10)
    thresholds: dict[str, int] = Field(default_factory=dict)
    axes: list[str] | None = None


def _to_case(item: EvalCaseRequest, index: int) -> EvalCase:
    return EvalCase(
        id=item.id or f"case-{index + 1}",
        task=item.task,
        model_output=item.model_output,
        reference=item.reference,
        rubric=item.rubric,
        metadata=item.metadata,
    )


def _build_judge(session: Session, current_user: User, body: EvalRunRequest) -> CallJudge:
    axes = tuple(body.axes) if body.axes else JUDGE_AXES
    try:
        return build_judge_from_settings(session, current_user.company_id, axes=axes, thresholds=body.thresholds)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/judge")
async def judge_cases(
    body: EvalRunRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    judge = _build_judge(session, current_user, body)
    cases = [_to_case(item, idx) for idx, item in enumerate(body.cases)]
    try:
        results = await judge.judge_batch(cases, concurrency=body.concurrency)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Judge failed: {exc}") from exc

    return {
        "provider": judge.provider,
        "model": judge.model,
        "summary": summarize_results(results),
        "results": [result.to_record() for result in results],
    }


# ---------------------------------------------------------------------------
# Per-call eval endpoints
# ---------------------------------------------------------------------------

def _eval_to_dict(r: CallEvalResult) -> dict[str, Any]:
    import json
    return {
        "id": r.id,
        "interaction_id": r.interaction_id,
        "lead_id": r.lead_id,
        "judge_provider": r.judge_provider,
        "judge_model": r.judge_model,
        "score_call_summary": r.score_call_summary,
        "score_lead_qualification": r.score_lead_qualification,
        "score_next_action": r.score_next_action,
        "score_tool_use_honesty": r.score_tool_use_honesty,
        "score_tone_brand": r.score_tone_brand,
        "score_handoff_escalation": r.score_handoff_escalation,
        "score_overall": r.score_overall,
        "passed": r.passed,
        "reasoning": r.reasoning,
        "failures": json.loads(r.failures_json) if r.failures_json else [],
        "ran_at": r.ran_at.isoformat() if r.ran_at else None,
    }


@router.get("/call/{interaction_id}")
async def get_call_eval(
    interaction_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    from services.evals.call_eval_service import get_call_eval as _get, run_call_eval as _run
    result = _get(session, interaction_id)
    if not result:
        from models.models import Interaction
        interaction = session.get(Interaction, interaction_id)
        if interaction and interaction.company_id == current_user.company_id and interaction.transcript:
            result = await _run(session, interaction_id, current_user.company_id)
    if not result:
        raise HTTPException(status_code=404, detail="No eval result for this interaction")
    return _eval_to_dict(result)


@router.post("/call/{interaction_id}/run")
async def run_call_eval(
    interaction_id: int,
    background_tasks: BackgroundTasks,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Trigger eval for a specific call interaction. Runs in background, returns 202."""
    from models.models import Interaction
    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")

    company_id = current_user.company_id

    async def _run():
        from services.evals.call_eval_service import run_call_eval as _eval
        from database import engine
        from sqlmodel import Session as _Session
        with _Session(engine) as s:
            await _eval(s, interaction_id, company_id)

    background_tasks.add_task(_run)
    return {"status": "queued", "interaction_id": interaction_id}


# ---------------------------------------------------------------------------
# Config endpoint — shows available providers
# ---------------------------------------------------------------------------

@router.get("/config")
async def eval_config(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    def _has(key: str) -> bool:
        return bool(get_company_setting_value(session, current_user.company_id, key))

    configured_provider = get_company_setting_value(session, current_user.company_id, "EVAL_JUDGE_PROVIDER") or ""
    configured_model = get_company_setting_value(session, current_user.company_id, "EVAL_JUDGE_MODEL") or ""

    available: list[str] = []
    if _has("MISTRAL_API_KEY"):
        available.append("mistral")
    if _has("OPENAI_API_KEY"):
        available.append("openai")
    if _has("GEMINI_API_KEY"):
        available.append("gemini")
    if _has("CLAUDE_API_KEY") or _has("ANTHROPIC_API_KEY"):
        available.append("claude")
    if _has("GROQ_API_KEY"):
        available.append("groq")

    active_provider = configured_provider or (available[0] if available else None)
    active_model = configured_model or (PROVIDER_DEFAULTS.get(active_provider, "") if active_provider else "")

    return {
        "active_provider": active_provider,
        "active_model": active_model,
        "available_providers": available,
        "provider_defaults": PROVIDER_DEFAULTS,
        "eval_axes": list(JUDGE_AXES),
        "default_thresholds": {
            "call_summary": 4,
            "lead_qualification": 4,
            "next_action": 4,
            "tool_use_honesty": 4,
            "tone_brand": 3,
            "handoff_escalation": 4,
        },
        "settings_keys": {
            "provider": "EVAL_JUDGE_PROVIDER",
            "model": "EVAL_JUDGE_MODEL",
        },
    }
