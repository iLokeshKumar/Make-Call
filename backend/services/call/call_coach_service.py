"""
AI Sales Coach Service

After every call:
  1. LLM scores the AI's performance across 5 sales dimensions (0-10 each).
  2. Identifies top strength and top weakness from the transcript.
  3. Generates a targeted system-prompt patch to fix the weakest dimension.
  4. Optionally auto-applies the patch to the company's SYSTEM_PROMPT setting
     if auto-tune is enabled (CompanySetting AUTO_COACH_TUNE = "true").

Dimensions scored:
  - Rapport       (opening energy, personalisation, warmth)
  - Discovery     (open questions, need-uncovering, listening signals)
  - Objection handling (acknowledgement, reframe, counter)
  - Value proposition (feature → benefit translation, ROI language)
  - Closing       (clear next step set, CTA confidence)
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlmodel import Session, select

from models.models import CallCoachScore, CompanySetting, Feedback, Lead, utc_now

logger = logging.getLogger(__name__)

COACH_PROMPT = """
You are an expert B2B sales coach evaluating an AI sales assistant's call performance.

Score each dimension 0-10 (10 = flawless), then give one sentence each for the strongest and
weakest moment, and a 2–3 sentence system-prompt patch that would fix the main weakness.

Return ONLY valid JSON — no markdown, no explanation outside JSON:
{
  "rapport": <int 0-10>,
  "discovery": <int 0-10>,
  "objection_handling": <int 0-10>,
  "value_proposition": <int 0-10>,
  "closing": <int 0-10>,
  "strengths": "<one sentence>",
  "weaknesses": "<one sentence>",
  "prompt_suggestion": "<2-3 sentence system-prompt patch — written in imperative/instruction style>"
}

Rules:
- Score 0 if dimension not applicable (e.g., call too short).
- prompt_suggestion must be directly usable as an appended instruction in a system prompt.
- Do not include markdown fences, do not include keys other than the 8 above.
"""


def _safe_parse(text: str) -> dict | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1).strip())
        except Exception:
            pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _weighted_overall(d: dict) -> int:
    weights = {
        "rapport": 1,
        "discovery": 2,
        "objection_handling": 2,
        "value_proposition": 2,
        "closing": 3,
    }
    total_w = sum(weights.values())
    score = sum(d.get(k, 0) * w for k, w in weights.items())
    return round(score / total_w)


def _is_auto_tune_enabled(session: Session, company_id: int) -> bool:
    from credentials_service import get_company_setting_value
    val = get_company_setting_value(session, company_id, "AUTO_COACH_TUNE")
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def _apply_prompt_patch(session: Session, company_id: int, patch: str, actor_user_id: int) -> None:
    """Append the coach's patch to the company SYSTEM_PROMPT setting."""
    setting = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == "SYSTEM_PROMPT",
        )
    ).first()

    if setting:
        current = setting.value or ""
        MARKER = "\n\n[AUTO-COACH PATCH]\n"
        # Remove previous coach patch before appending new one
        if MARKER in current:
            current = current[:current.index(MARKER)]
        setting.value = current + MARKER + patch
        setting.updated_at = utc_now()
        setting.updated_by = actor_user_id
        session.add(setting)
    else:
        session.add(CompanySetting(
            company_id=company_id,
            key="SYSTEM_PROMPT",
            value="You are Rio, a concise inside-sales voice assistant.\n\n[AUTO-COACH PATCH]\n" + patch,
            is_secret=False,
            created_by=actor_user_id,
            updated_by=actor_user_id,
        ))

    session.commit()
    logger.info("[Coach] System prompt auto-patched for company %s", company_id)


async def score_call_and_coach(
    session: Session,
    llm_service,
    company_id: int,
    actor_user_id: int,
    interaction_id: int,
    lead_id: Optional[int],
    transcript: str,
) -> Optional[CallCoachScore]:
    """
    Score the AI's performance and optionally auto-tune the system prompt.
    Returns the persisted CallCoachScore (or None on failure).
    """
    if not transcript or len(transcript.strip()) < 50:
        logger.info("[Coach] Transcript too short for scoring (interaction %s)", interaction_id)
        return None

    # Skip if already scored
    existing = session.exec(
        select(CallCoachScore).where(
            CallCoachScore.interaction_id == interaction_id,
        )
    ).first()
    if existing:
        return existing

    # Pull customer's verbal feedback for this call (if any) so the coach's
    # prompt_suggestion is informed by the customer's actual voice, not just
    # the LLM's read of the transcript.
    customer_voice = ""
    fb = session.exec(
        select(Feedback).where(
            Feedback.company_id == company_id,
            Feedback.interaction_id == interaction_id,
            Feedback.source == "customer",
        ).limit(1)
    ).first()
    if fb:
        bits = []
        if fb.rating is not None:
            bits.append(f"Customer rating: {fb.rating}/5")
        if fb.comment:
            bits.append(f"Customer comment: {fb.comment.strip()[:300]}")
        if bits:
            customer_voice = "\n\nCUSTOMER VERBAL FEEDBACK:\n" + "\n".join(bits)

    prompt = f"{COACH_PROMPT}{customer_voice}\n\nCALL TRANSCRIPT:\n{transcript[:4000]}"

    try:
        llm_service.add_user_message(prompt)
        result_text = ""
        async for chunk in llm_service.stream():
            if chunk.get("type") == "finished":
                result_text = chunk.get("full_reply", result_text)
                break
            elif chunk.get("type") == "token":
                result_text += chunk.get("content", "")

        data = _safe_parse(result_text)
        if not data:
            logger.error(
                "[Coach] LLM returned unparseable response for interaction %s. Raw reply (%d chars): %r",
                interaction_id, len(result_text), result_text[:500],
            )
            return None

        overall = _weighted_overall(data)
        score = CallCoachScore(
            company_id=company_id,
            interaction_id=interaction_id,
            lead_id=lead_id,
            score_rapport=data.get("rapport"),
            score_discovery=data.get("discovery"),
            score_objection_handling=data.get("objection_handling"),
            score_value_proposition=data.get("value_proposition"),
            score_closing=data.get("closing"),
            score_overall=overall,
            strengths=data.get("strengths"),
            weaknesses=data.get("weaknesses"),
            prompt_suggestion=data.get("prompt_suggestion"),
            created_by=actor_user_id,
            updated_by=actor_user_id,
        )
        session.add(score)
        session.commit()
        session.refresh(score)

        logger.info(
            "[Coach] Scored interaction %s: overall=%s/10 (rapport=%s disc=%s obj=%s vp=%s close=%s)",
            interaction_id, overall,
            data.get("rapport"), data.get("discovery"),
            data.get("objection_handling"), data.get("value_proposition"),
            data.get("closing"),
        )

        # Auto-tune system prompt if enabled and score is below threshold
        if (
            overall < 7
            and data.get("prompt_suggestion")
            and _is_auto_tune_enabled(session, company_id)
        ):
            _apply_prompt_patch(session, company_id, data["prompt_suggestion"], actor_user_id)
            score.prompt_applied = True
            session.add(score)
            session.commit()

        return score

    except Exception as exc:
        logger.error("[Coach] Scoring failed for interaction %s: %s", interaction_id, exc, exc_info=True)
        return None


def get_recent_coach_scores(
    session: Session,
    company_id: int,
    limit: int = 20,
) -> list[CallCoachScore]:
    return session.exec(
        select(CallCoachScore)
        .where(CallCoachScore.company_id == company_id)
        .order_by(CallCoachScore.created_at.desc())
        .limit(limit)
    ).all()


def get_coach_score_for_interaction(
    session: Session,
    company_id: int,
    interaction_id: int,
) -> Optional[CallCoachScore]:
    return session.exec(
        select(CallCoachScore).where(
            CallCoachScore.company_id == company_id,
            CallCoachScore.interaction_id == interaction_id,
        )
    ).first()


def get_coach_averages(session: Session, company_id: int) -> dict:
    """Return average dimension scores across all scored calls."""
    scores = session.exec(
        select(CallCoachScore).where(
            CallCoachScore.company_id == company_id,
            CallCoachScore.score_overall.is_not(None),
        )
    ).all()

    if not scores:
        return {}

    def avg(vals):
        clean = [v for v in vals if v is not None]
        return round(sum(clean) / len(clean), 1) if clean else None

    # Recent low-CSAT signal: customer-given verbal ratings ≤ 2 (last 30 rows).
    # Surfaced in the coach panel so reps see customer voice alongside LLM scoring.
    # JOIN to Lead so soft-deleted leads' feedback is hidden from analytics —
    # otherwise a deleted noisy lead keeps poisoning the coach panel.  LEFT
    # OUTER JOIN preserves rows where lead_id is null (legacy data).
    low_csat = session.exec(
        select(Feedback)
        .outerjoin(Lead, Lead.id == Feedback.lead_id)
        .where(
            Feedback.company_id == company_id,
            Feedback.source == "customer",
            Feedback.feedback_type == "csat",
            Feedback.rating <= 2,
            (Lead.deleted_at.is_(None)) | (Feedback.lead_id.is_(None)),
        )
        .order_by(Feedback.created_at.desc())
        .limit(30)
    ).all()
    csat_avg = session.exec(
        select(Feedback)
        .outerjoin(Lead, Lead.id == Feedback.lead_id)
        .where(
            Feedback.company_id == company_id,
            Feedback.source == "customer",
            Feedback.feedback_type == "csat",
            Feedback.rating.is_not(None),
            (Lead.deleted_at.is_(None)) | (Feedback.lead_id.is_(None)),
        )
    ).all()
    csat_ratings = [f.rating for f in csat_avg if f.rating is not None]

    return {
        "total_calls_scored": len(scores),
        "avg_overall": avg([s.score_overall for s in scores]),
        "avg_rapport": avg([s.score_rapport for s in scores]),
        "avg_discovery": avg([s.score_discovery for s in scores]),
        "avg_objection_handling": avg([s.score_objection_handling for s in scores]),
        "avg_value_proposition": avg([s.score_value_proposition for s in scores]),
        "avg_closing": avg([s.score_closing for s in scores]),
        "auto_tune_applied_count": sum(1 for s in scores if s.prompt_applied),
        "csat_count": len(csat_ratings),
        "csat_avg": round(sum(csat_ratings) / len(csat_ratings), 2) if csat_ratings else None,
        "recent_low_csat": [
            {
                "interaction_id": f.interaction_id,
                "lead_id": f.lead_id,
                "rating": f.rating,
                "comment": (f.comment or "")[:200],
                "created_at": f.created_at.isoformat() if f.created_at else None,
            }
            for f in low_csat
        ],
    }
