"""
Objection Library Service

Two responsibilities:
1. EXTRACT – after a call, parse the transcript with an LLM to identify
   objections raised by the prospect and save/upsert them to ObjectionEntry.

2. INJECT – at the start of a call, load the top objections for the company
   and return a formatted string to append to the system prompt so Rio knows
   how to handle them.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from sqlmodel import Session, select

from models.models import ObjectionEntry, utc_now

logger = logging.getLogger(__name__)

# Extraction

OBJECTION_EXTRACTION_PROMPT = """
You are analysing a B2B sales call transcript to extract objections raised by the prospect.

Return ONLY a valid JSON array (no markdown, no explanation):
[
  {
    "objection_key": "short canonical phrase (≤10 words, lowercase)",
    "objection_text": "the actual words the prospect used or a short paraphrase",
    "category": "price|competitor|timing|need|general",
    "rebuttal_used": "what the sales agent said in response, or null"
  }
]

Rules:
- Only include genuine sales objections (not questions or neutral statements).
- category meanings: price=cost/budget concern, competitor=mentions rival product,
  timing=not the right time, need=doesn't need the product, general=other objection.
- If no objections exist, return [].
- objection_key must be canonical and reusable across calls (e.g. "too expensive",
  "already using competitor", "need approval from management").
"""


def _safe_parse(text: str) -> list[dict]:
    if not text:
        return []
    try:
        return json.loads(text)
    except Exception:
        pass
    match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception:
            pass
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    return []


async def extract_and_save_objections(
    session: Session,
    llm_service,
    company_id: int,
    actor_user_id: int,
    interaction_id: int,
    transcript: str,
) -> list[ObjectionEntry]:
    """
    Extract objections from a call transcript and upsert them into the library.
    Returns the list of upserted ObjectionEntry records.
    """
    if not transcript or not transcript.strip():
        return []

    saved: list[ObjectionEntry] = []
    try:
        prompt = f"{OBJECTION_EXTRACTION_PROMPT}\n\nCALL TRANSCRIPT:\n{transcript}\n"
        llm_service.add_user_message(prompt)

        result_text = ""
        async for chunk in llm_service.stream():
            if chunk.get("type") == "finished":
                result_text = chunk.get("full_reply", result_text)
                break
            elif chunk.get("type") == "token":
                result_text += chunk.get("content", "")

        items = _safe_parse(result_text)
        if not isinstance(items, list):
            logger.warning("[ObjectionService] LLM returned non-list: %s", result_text[:200])
            return []

        for item in items:
            if not isinstance(item, dict):
                continue
            key = (item.get("objection_key") or "").strip().lower()[:200]
            text = (item.get("objection_text") or key).strip()[:500]
            category = (item.get("category") or "general").strip()[:50]
            rebuttal = item.get("rebuttal_used") or None

            if not key:
                continue

            # Upsert: if we already have this key for the company, increment count
            existing = session.exec(
                select(ObjectionEntry).where(
                    ObjectionEntry.company_id == company_id,
                    ObjectionEntry.objection_key == key,
                )
            ).first()

            if existing:
                existing.frequency_count += 1
                existing.updated_at = utc_now()
                existing.updated_by = actor_user_id
                # Only overwrite rebuttal if extraction returned one and the existing rebuttal hasn't been manually edited (heuristic: keep it if frequency > 3, meaning an admin probably tuned it).
                if rebuttal and existing.frequency_count <= 3:
                    existing.rebuttal = rebuttal
                session.add(existing)
                saved.append(existing)
            else:
                entry = ObjectionEntry(
                    company_id=company_id,
                    objection_key=key,
                    objection_text=text,
                    category=category,
                    rebuttal=rebuttal,
                    frequency_count=1,
                    source_interaction_id=interaction_id,
                    is_active=True,
                    created_by=actor_user_id,
                    updated_by=actor_user_id,
                )
                session.add(entry)
                saved.append(entry)

        session.commit()
        logger.info(
            "[ObjectionService] Saved %d objections for company %d (interaction %d)",
            len(saved), company_id, interaction_id,
        )
    except Exception as exc:
        logger.warning("[ObjectionService] Extraction failed: %s", exc)

    return saved


# Injection

def get_objection_playbook(
    session: Session,
    company_id: int,
    limit: int = 12,
) -> str:
    """
    Return a formatted string to append to the voice pipeline system prompt.
    Only includes active entries that have a rebuttal.
    Ordered by frequency (most common first) so the most impactful ones are
    within the context window.
    """
    entries = session.exec(
        select(ObjectionEntry)
        .where(
            ObjectionEntry.company_id == company_id,
            ObjectionEntry.is_active == True,
            ObjectionEntry.rebuttal.isnot(None),  # type: ignore[arg-type]
        )
        .order_by(ObjectionEntry.frequency_count.desc())
        .limit(limit)
    ).all()

    if not entries:
        return ""

    lines = [
        "\n\n### OBJECTION HANDLING PLAYBOOK",
        "When a prospect raises one of the following objections, use the suggested rebuttal as a guide:",
    ]
    for entry in entries:
        lines.append(
            f'- "{entry.objection_text}" → {entry.rebuttal}'
        )

    return "\n".join(lines)
