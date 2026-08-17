"""Per-call LLM-as-judge evaluation using real transcript + CRM data.

Builds 6 eval cases from actual call artifacts, runs judge, persists CallEvalResult.
Auto-triggered post-call. Can also be triggered on-demand via API.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from sqlmodel import Session, select

from models.models import CallEvalResult, CallTask, Interaction, Lead, utc_now

logger = logging.getLogger(__name__)

# Rubrics per axis
_RUBRICS = {
    "call_summary": (
        "The summary must accurately capture: customer intent, key objections, "
        "commitments made, and next steps. No invented facts. No important omissions."
    ),
    "lead_qualification": (
        "Qualification status must match evidence in the transcript. "
        "BANT signals (budget/authority/need/timeline) should be reflected. "
        "Penalize over-qualification or under-qualification."
    ),
    "next_action": (
        "The recommended next action must follow logically from the call outcome "
        "and lead signals. It should be specific and time-bound where data allows. "
        "Generic or missing next actions score low."
    ),
    "tool_use_honesty": (
        "The AI agent must not fabricate product specs, pricing, or commitments "
        "not in the reference data. Penalize any unsupported claims made to the lead."
    ),
    "tone_brand": (
        "The agent's language must be professional, empathetic, and on-brand. "
        "Penalize robotic phrasing, excessive filler, rudeness, or off-brand tone."
    ),
    "handoff_escalation": (
        "If the lead requested a human or escalation, it must be acknowledged. "
        "If no escalation was needed, verify the call closed with a clear CTA. "
        "Penalize missed escalation cues or ambiguous call endings."
    ),
}


def _safe_truncate(text: str | None, max_chars: int = 3000) -> str:
    if not text:
        return "(no data)"
    return text[:max_chars] if len(text) > max_chars else text


def _extract_call_summary(session: Session, interaction: Interaction) -> str | None:
    """Look for a call_summary interaction linked to the same lead around the same call."""
    if not interaction.lead_id:
        return None
    stmt = (
        select(Interaction)
        .where(
            Interaction.lead_id == interaction.lead_id,
            Interaction.company_id == interaction.company_id,
            Interaction.type == "call_summary",
        )
        .order_by(Interaction.created_at.desc())
        .limit(1)
    )
    summary_i = session.exec(stmt).first()
    if summary_i:
        return summary_i.content or summary_i.transcript
    # Fallback: check metadata_json on the call interaction itself
    meta = interaction.metadata_json or {}
    return meta.get("summary") or meta.get("call_summary")


def _extract_lead_context(lead: Lead) -> str:
    parts = [f"Status: {lead.status}"]
    if lead.qualification_status:
        parts.append(f"Qualification: {lead.qualification_status}")
    if lead.ism_stage:
        parts.append(f"ISM stage: {lead.ism_stage}")
    for attr in ("budget_range", "timeline", "decision_maker", "product_interest"):
        v = getattr(lead, attr, None)
        if v:
            parts.append(f"{attr}: {v}")
    return "; ".join(parts)


def build_eval_cases(
    interaction: Interaction,
    lead: Lead | None,
    call_summary_text: str | None,
) -> list[dict[str, Any]]:
    """Build 6 eval case dicts from real call artifacts. Skip axes with no data."""
    transcript = interaction.transcript or ""
    meta = interaction.metadata_json or {}
    cases: list[dict[str, Any]] = []

    # 1. call_summary — compare saved summary vs transcript
    summary = call_summary_text or meta.get("summary") or ""
    if summary and transcript:
        cases.append({
            "axis": "call_summary",
            "task": "Evaluate if this call summary accurately captures the conversation.",
            "reference": _safe_truncate(transcript),
            "model_output": _safe_truncate(summary, 1500),
            "rubric": _RUBRICS["call_summary"],
        })

    # 2. lead_qualification — compare lead status vs transcript evidence
    if lead and transcript:
        lead_ctx = _extract_lead_context(lead)
        cases.append({
            "axis": "lead_qualification",
            "task": "Evaluate if the lead qualification decision matches call evidence.",
            "reference": _safe_truncate(transcript),
            "model_output": lead_ctx,
            "rubric": _RUBRICS["lead_qualification"],
        })

    # 3. next_action — compare recommended next action vs call signals
    next_action = (lead.next_action if lead else None) or meta.get("next_action") or ""
    if next_action and transcript:
        cases.append({
            "axis": "next_action",
            "task": "Evaluate if the next action recommendation is appropriate for this call.",
            "reference": _safe_truncate(transcript, 2000),
            "model_output": next_action,
            "rubric": _RUBRICS["next_action"],
        })

    # 4. tool_use_honesty — check AI turns for fabricated claims
    if transcript:
        # Extract agent turns where possible; fall back to full transcript
        agent_turns = _extract_agent_turns(transcript)
        cases.append({
            "axis": "tool_use_honesty",
            "task": (
                "Evaluate if the AI agent stayed factual and did not fabricate "
                "product specs, pricing, or commitments not in the reference data."
            ),
            "reference": "The agent should only reference information explicitly asked by the lead or confirmed by the company context. No invented pricing, dates, or guarantees.",
            "model_output": _safe_truncate(agent_turns, 2000),
            "rubric": _RUBRICS["tool_use_honesty"],
        })

    # 5. tone_brand — evaluate professionalism from transcript
    if transcript:
        cases.append({
            "axis": "tone_brand",
            "task": "Evaluate if the AI agent's tone was professional, empathetic, and on-brand.",
            "reference": "Expected: professional, warm, concise. Avoid: robotic repetition, pushy closing, excessive filler words.",
            "model_output": _safe_truncate(_extract_agent_turns(transcript), 2000),
            "rubric": _RUBRICS["tone_brand"],
        })

    # 6. handoff_escalation — check call ending for clear CTA or escalation
    if transcript:
        ending = transcript[-1500:] if len(transcript) > 1500 else transcript
        cases.append({
            "axis": "handoff_escalation",
            "task": "Evaluate if the call ended with a clear next step or proper escalation.",
            "reference": "The agent must close with a confirmed action (callback time, demo booked, email to follow). If the lead asked for a human, it must be acknowledged.",
            "model_output": _safe_truncate(ending, 1500),
            "rubric": _RUBRICS["handoff_escalation"],
        })

    return cases


def _extract_agent_turns(transcript: str) -> str:
    """Extract lines likely spoken by the AI agent (heuristic: 'Agent:' or 'AI:' prefix)."""
    lines = transcript.splitlines()
    agent_lines = [
        l for l in lines
        if l.lower().startswith(("agent:", "ai:", "bot:", "assistant:", "rio:"))
    ]
    if agent_lines:
        return "\n".join(agent_lines)
    # If no role markers, return full transcript (judge will assess overall)
    return transcript


async def run_call_eval(
    session: Session,
    interaction_id: int,
    company_id: int,
) -> CallEvalResult | None:
    """Build cases from real data, judge them, persist and return CallEvalResult."""
    from services.evals.llm_judge import build_judge_from_settings

    # Load interaction
    interaction = session.get(Interaction, interaction_id)
    if not interaction:
        logger.warning("[CallEval] interaction %s not found", interaction_id)
        return None
    if not interaction.transcript:
        logger.info("[CallEval] interaction %s has no transcript, skipping eval", interaction_id)
        return None

    # Load lead
    lead = session.get(Lead, interaction.lead_id) if interaction.lead_id else None

    # Load call summary text
    call_summary_text = _extract_call_summary(session, interaction)

    # Build eval cases
    raw_cases = build_eval_cases(interaction, lead, call_summary_text)
    if not raw_cases:
        logger.info("[CallEval] no eval cases for interaction %s", interaction_id)
        return None

    # Build judge
    try:
        judge = build_judge_from_settings(session, company_id)
    except ValueError as exc:
        logger.warning("[CallEval] no judge available: %s", exc)
        return None

    # Score each axis independently: one LLM call per axis with a single-axis judge
    from services.evals.llm_judge import EvalCase, CallJudge

    axis_scores: dict[str, int] = {}
    all_failures: list[str] = []
    reasoning_parts: list[str] = []

    async def _score_axis(c: dict) -> None:
        axis = c["axis"]
        single_judge = CallJudge(
            provider=judge.provider,
            api_key=judge.api_key,
            model=judge.model,
            axes=(axis,),
            thresholds={axis: judge.thresholds.get(axis, 4)},
        )
        case = EvalCase(
            id=f"{interaction_id}_{axis}",
            task=c["task"],
            model_output=c["model_output"],
            reference=c["reference"],
            rubric=c["rubric"],
            metadata={"axis": axis},
        )
        import asyncio as _aio
        for attempt in range(3):
            try:
                result = await single_judge.judge(case)
                score = result.scores.get(axis, 1)
                axis_scores[axis] = score
                if not result.pass_:
                    all_failures.append(axis)
                if result.reasoning:
                    reasoning_parts.append(f"[{axis}] {result.reasoning}")
                break
            except Exception as exc:
                is_rate_limit = "429" in str(exc) or "rate" in str(exc).lower()
                if is_rate_limit and attempt < 2:
                    wait = 8 * (attempt + 1)  # 8s, 16s
                    logger.info("[CallEval] axis=%s rate-limited, retry in %ds", axis, wait)
                    await _aio.sleep(wait)
                else:
                    logger.warning("[CallEval] axis=%s failed: %s", axis, exc)
                    axis_scores[axis] = 1
                    all_failures.append(axis)
                    break

    for c in raw_cases:
        await _score_axis(c)

    def _get_score(axis: str) -> int | None:
        return axis_scores.get(axis)

    scored = [s for s in axis_scores.values() if s is not None]
    overall = round(sum(scored) / len(scored), 2) if scored else None
    passed = len(all_failures) == 0

    reasoning = " | ".join(reasoning_parts)[:3000]

    # Upsert CallEvalResult
    existing = session.exec(
        select(CallEvalResult).where(CallEvalResult.interaction_id == interaction_id)
    ).first()

    if existing:
        record = existing
    else:
        record = CallEvalResult(
            company_id=company_id,
            interaction_id=interaction_id,
            lead_id=interaction.lead_id,
        )

    record.judge_provider = judge.provider
    record.judge_model = judge.model
    record.score_call_summary = _get_score("call_summary")
    record.score_lead_qualification = _get_score("lead_qualification")
    record.score_next_action = _get_score("next_action")
    record.score_tool_use_honesty = _get_score("tool_use_honesty")
    record.score_tone_brand = _get_score("tone_brand")
    record.score_handoff_escalation = _get_score("handoff_escalation")
    record.score_overall = overall
    record.passed = passed
    record.reasoning = reasoning
    record.failures_json = json.dumps(all_failures)
    record.ran_at = utc_now()
    record.updated_at = utc_now()

    session.add(record)
    session.commit()
    session.refresh(record)

    logger.info(
        "[CallEval] interaction=%s provider=%s overall=%.2f passed=%s failures=%s",
        interaction_id, judge.provider, overall or 0, passed, all_failures,
    )
    return record


def get_call_eval(session: Session, interaction_id: int) -> CallEvalResult | None:
    return session.exec(
        select(CallEvalResult).where(CallEvalResult.interaction_id == interaction_id)
    ).first()
