"""
Real-time sentiment broadcaster — PostgreSQL-backed pub/sub.

Events are written to the `sentiment_events` table so they are visible
to all uvicorn workers. The WebSocket handler polls the table every 200ms
using a cursor (last_id) instead of an in-process asyncio.Queue.

Usage:
  # In VoicePipeline (after each final STT transcript):
  await sentiment_broadcaster.publish(interaction_id, sentiment_data, company_id)

  # In WebSocket route handler — see main.py /ws/sentiment/{interaction_id}
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# sentiment keyword banks
_POSITIVE = {
    "interested", "yes", "tell me", "send", "share", "proposal",
    "pricing", "demo", "meeting", "available", "excited",
    "let's do", "sounds good", "schedule demo", "send quote",
    "definitely", "perfect", "great", "absolutely", "sure",
    "please", "want to", "love to", "happy to",
}
_NEGATIVE = {
    "not interested", "no", "stop", "remove", "unsubscribe", "not now",
    "later", "busy", "wrong", "no thanks", "not good", "don't call",
    "already have", "not looking", "not relevant", "waste", "don't need",
    "too expensive", "can't afford",
}
_OBJECTION = {
    "too expensive", "already have", "need to think", "call me later",
    "not the right time", "budget constraint", "using competitor",
    "satisfied with current",
}


def analyze_sentiment(text: str) -> dict:
    """
    Instant keyword-based sentiment analysis. Zero latency — no LLM call.
    Returns: {score: 0-100, label: positive|neutral|negative|objection, snippet: str}
    """
    text_lower = text.lower()

    objection_hits = sum(1 for phrase in _OBJECTION if phrase in text_lower)
    positive_hits  = sum(1 for phrase in _POSITIVE  if phrase in text_lower)
    negative_hits  = sum(1 for phrase in _NEGATIVE  if phrase in text_lower)

    if objection_hits:
        score = max(15, 40 - objection_hits * 10)
        label = "objection"
    elif positive_hits > negative_hits:
        score = min(95, 55 + positive_hits * 12)
        label = "positive"
    elif negative_hits > positive_hits:
        score = max(5, 45 - negative_hits * 15)
        label = "negative"
    else:
        score = 50
        label = "neutral"

    return {
        "score": score,
        "label": label,
        "snippet": text[:100],
    }


async def publish(interaction_id: str, data: dict, company_id: int) -> None:
    """
    Write a sentiment event to PostgreSQL.
    Works across all uvicorn workers — no shared in-process state.
    """
    try:
        from database import engine as _db_engine
        from sqlmodel import Session as _DbSession
        from models.models import SentimentEvent

        with _DbSession(_db_engine) as s:
            s.add(SentimentEvent(
                interaction_id=str(interaction_id),
                company_id=company_id,
                payload=data,
            ))
            s.commit()
    except Exception as exc:
        logger.debug("Sentiment DB write skipped: %s", exc)
