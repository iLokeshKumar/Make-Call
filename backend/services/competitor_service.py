"""
Competitor Mention Detection Service

Two detection modes:
  1. Real-time (voice pipeline): keyword matching against a configurable list
  2. Post-call (LLM): structured extraction from the full transcript

Counter-script injection:
  When a competitor is detected, the pipeline fetches the matching counter_script
  (if any) and appends it to the LLM system prompt so the AI can respond tactfully.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from sqlmodel import Session, select

from models.models import CompetitorMention, utc_now

logger = logging.getLogger(__name__)

# Default competitor list used when no company-specific list is configured.
# Companies can override this via CompanySetting key "COMPETITOR_NAMES" (comma-separated).
DEFAULT_COMPETITORS = [
    "salesforce", "hubspot", "zoho", "pipedrive", "freshsales",
    "leadsquared", "kylas", "sugar crm", "microsoft dynamics",
    "zendesk", "intercom", "close", "outreach", "salesloft",
]


def _load_competitor_names(session: Session, company_id: int) -> list[str]:
    from credentials_service import get_company_setting_value
    custom = get_company_setting_value(session, company_id, "COMPETITOR_NAMES")
    if custom:
        return [c.strip().lower() for c in custom.split(",") if c.strip()]
    return DEFAULT_COMPETITORS


# Real-time detection (called per-utterance from voice pipeline)

def detect_competitors_in_utterance(
    session: Session,
    company_id: int,
    lead_id: Optional[int],
    interaction_id: Optional[int],
    utterance: str,
) -> list[CompetitorMention]:
    """
    Scan a single utterance for competitor keywords.
    Saves a CompetitorMention row for each new match.
    Returns the list of newly created mentions (empty if none found).
    """
    if not utterance:
        return []

    text_lower = utterance.lower()
    competitor_names = _load_competitor_names(session, company_id)
    new_mentions: list[CompetitorMention] = []

    for name in competitor_names:
        # Word-boundary match to avoid "close" matching "closely"
        pattern = r"\b" + re.escape(name) + r"\b"
        match = re.search(pattern, text_lower)
        if not match:
            continue

        snippet = utterance[max(0, match.start() - 40): match.end() + 40].strip()

        mention = CompetitorMention(
            company_id=company_id,
            lead_id=lead_id,
            interaction_id=interaction_id,
            competitor_name=name,
            mention_snippet=snippet[:500],
            source="realtime",
            detected_at=utc_now(),
        )
        session.add(mention)
        new_mentions.append(mention)
        logger.info(
            "[CompetitorDetect] %s mentioned on interaction %s — snippet: %s",
            name, interaction_id, snippet[:80],
        )

    if new_mentions:
        session.commit()
        for m in new_mentions:
            session.refresh(m)

    return new_mentions


# Counter-script injection (voice pipeline)

def get_counter_script_injection(
    session: Session,
    company_id: int,
    competitor_name: str,
) -> Optional[str]:
    """
    Return a formatted counter-script string for appending to the LLM system prompt.
    Returns None if no counter script is configured for this competitor.
    """
    # Look for any existing mention that has a counter_script for this competitor
    mention = session.exec(
        select(CompetitorMention).where(
            CompetitorMention.company_id == company_id,
            CompetitorMention.competitor_name == competitor_name.lower(),
            CompetitorMention.counter_script.is_not(None),
        ).order_by(CompetitorMention.created_at.desc())
    ).first()

    if not mention or not mention.counter_script:
        return None

    return (
        f"\n\n[COMPETITOR DETECTED: {competitor_name.upper()}]\n"
        f"Counter-script: {mention.counter_script}\n"
        f"Use this tactfully if the prospect mentions {competitor_name}."
    )


# Post-call LLM extraction

async def extract_and_save_competitor_mentions(
    session: Session,
    llm_service,
    company_id: int,
    lead_id: Optional[int],
    interaction_id: int,
    transcript: str,
) -> list[CompetitorMention]:
    """
    Use the LLM to extract competitor mentions from the full transcript.
    More accurate than keyword matching; run post-call.
    """
    if not transcript or not transcript.strip():
        return []

    prompt = (
        "You are analyzing a B2B sales call transcript to detect competitor mentions.\n\n"
        "Return ONLY a JSON array (no markdown). Each element:\n"
        '{"competitor": "<name>", "snippet": "<exact quote from transcript, max 100 chars>"}\n\n'
        "If no competitors are mentioned, return []\n\n"
        f"TRANSCRIPT:\n{transcript[:3000]}"
    )

    try:
        llm_service.add_user_message(prompt)
        result_text = ""
        async for chunk in llm_service.stream():
            if chunk.get("type") == "finished":
                result_text = chunk.get("full_reply", result_text)
                break
            elif chunk.get("type") == "token":
                result_text += chunk.get("content", "")

        import json, re as _re
        # Strip markdown fences
        cleaned = _re.sub(r"```(?:json)?", "", result_text).strip().strip("`")
        items = json.loads(cleaned) if cleaned else []

        saved: list[CompetitorMention] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("competitor"):
                continue
            mention = CompetitorMention(
                company_id=company_id,
                lead_id=lead_id,
                interaction_id=interaction_id,
                competitor_name=item["competitor"].lower()[:200],
                mention_snippet=(item.get("snippet") or "")[:500],
                source="post_call",
                detected_at=utc_now(),
            )
            session.add(mention)
            saved.append(mention)

        if saved:
            session.commit()
            for m in saved:
                session.refresh(m)
            logger.info(
                "[CompetitorDetect] Post-call extracted %d mentions on interaction %s",
                len(saved), interaction_id,
            )

        return saved

    except Exception as exc:
        logger.warning("[CompetitorDetect] Post-call extraction failed: %s", exc)
        return []


# API helpers

def get_competitor_mentions_for_lead(
    session: Session,
    company_id: int,
    lead_id: int,
    limit: int = 50,
) -> list[CompetitorMention]:
    return session.exec(
        select(CompetitorMention).where(
            CompetitorMention.company_id == company_id,
            CompetitorMention.lead_id == lead_id,
        ).order_by(CompetitorMention.detected_at.desc()).limit(limit)
    ).all()


def get_competitor_summary(
    session: Session,
    company_id: int,
) -> list[dict]:
    """Return aggregated mention counts per competitor."""
    mentions = session.exec(
        select(CompetitorMention).where(
            CompetitorMention.company_id == company_id,
        )
    ).all()

    counts: dict[str, int] = {}
    for m in mentions:
        counts[m.competitor_name] = counts.get(m.competitor_name, 0) + 1

    return sorted(
        [{"competitor": k, "count": v} for k, v in counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )


def upsert_counter_script(
    session: Session,
    company_id: int,
    competitor_name: str,
    counter_script: str,
    actor_user_id: int,
) -> CompetitorMention:
    """Store or update a counter-script for a competitor (creates a sentinel row)."""
    existing = session.exec(
        select(CompetitorMention).where(
            CompetitorMention.company_id == company_id,
            CompetitorMention.competitor_name == competitor_name.lower(),
            CompetitorMention.counter_script.is_not(None),
        )
    ).first()

    if existing:
        existing.counter_script = counter_script
        existing.updated_at = utc_now()
        existing.updated_by = actor_user_id
        session.add(existing)
        session.commit()
        session.refresh(existing)
        return existing

    mention = CompetitorMention(
        company_id=company_id,
        competitor_name=competitor_name.lower()[:200],
        counter_script=counter_script,
        source="manual",
        detected_at=utc_now(),
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(mention)
    session.commit()
    session.refresh(mention)
    return mention
