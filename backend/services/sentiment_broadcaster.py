"""
Real-time sentiment broadcaster.

Lightweight in-process pub/sub for streaming sentiment updates from the
VoicePipeline to any connected dashboard WebSocket clients.

Usage:
  # In VoicePipeline (after each final STT transcript):
  await sentiment_broadcaster.publish(interaction_id, sentiment_data)

  # In WebSocket route handler:
  queue = await sentiment_broadcaster.subscribe(interaction_id)
  try:
      while True:
          data = await asyncio.wait_for(queue.get(), timeout=30)
          await ws.send_json(data)
  finally:
      sentiment_broadcaster.unsubscribe(interaction_id, queue)
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

logger = logging.getLogger(__name__)

# sentiment keyword banks (reuse outcome_service signal sets via inline copy to avoid circular imports)
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


# pub/sub state

_subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)


async def subscribe(interaction_id: str) -> asyncio.Queue:
    """Register a new subscriber for the given interaction. Returns a queue."""
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers[interaction_id].append(q)
    logger.debug("[Sentiment] Subscribed to interaction %s", interaction_id)
    return q


def unsubscribe(interaction_id: str, queue: asyncio.Queue) -> None:
    """Remove a subscriber queue when the WebSocket disconnects."""
    subs = _subscribers.get(interaction_id)
    if subs:
        try:
            subs.remove(queue)
        except ValueError:
            pass
        if not subs:
            _subscribers.pop(interaction_id, None)
    logger.debug("[Sentiment] Unsubscribed from interaction %s", interaction_id)


async def publish(interaction_id: str, data: dict) -> None:
    """Publish a sentiment update to all subscribers of an interaction."""
    subs = _subscribers.get(str(interaction_id), [])
    for q in list(subs):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass  # dashboard is too slow — drop silently
