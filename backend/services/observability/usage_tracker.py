"""
Lightweight helper for recording AI service usage (tokens, characters, seconds)
to the usage_events table.  Fire-and-forget: never raises, always logs on error.

Usage:
    record_usage(session, service_type="llm", provider="groq",
                 model="llama-3.3-70b", prompt_tokens=120, completion_tokens=85,
                 company_id=1, interaction_id=42, context="voice_turn")
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def record_usage(
    session,
    *,
    service_type: str,
    provider: str,
    model: Optional[str] = None,
    prompt_tokens: Optional[int] = None,
    completion_tokens: Optional[int] = None,
    total_tokens: Optional[int] = None,
    characters: Optional[int] = None,
    audio_seconds: Optional[float] = None,
    company_id: Optional[int] = None,
    user_id: Optional[int] = None,
    interaction_id: Optional[int] = None,
    context: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    try:
        from models.models import UsageEvent

        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        event = UsageEvent(
            company_id=company_id,
            user_id=user_id,
            interaction_id=interaction_id,
            service_type=service_type,
            provider=provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            characters=characters,
            audio_seconds=audio_seconds,
            context=context,
            meta=meta,
        )
        session.add(event)
        session.commit()
    except Exception as exc:
        logger.warning("usage_tracker: failed to record %s/%s usage: %s", service_type, provider, exc)
