"""
Inbound reply classifier — hybrid rule fast path + Mistral LLM fallback.

Rule path: reuses services.communication.inbound_whatsapp_service.classify_reply_intent
(existing keyword matcher) for obvious intents — opt-out, clear interest, quote
requests, etc.  Returns in microseconds, no tokens.

LLM fallback: when the rule returns "neutral" and the body is long enough to be
worth classifying, call Mistral to bucket the reply into the roadmap's 5 classes:
{interested, objection, unsubscribe, question, noise}.

Responses are cached by sha256(body[:500]) for 1h so retries and duplicate
webhook deliveries don't re-invoke the LLM.

The LLM call is globally throttled — post-call pipeline also uses Mistral at
1.2s intervals, and the same free-tier rate limit affects both.  A module-level
monotonic counter falls back to rule-only after N classifications per rolling
cycle (default 3) to keep the free-tier bucket from being drained.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from typing import Any

from sqlmodel import Session

from services.communication.inbound_whatsapp_service import classify_reply_intent

logger = logging.getLogger(__name__)


# Intent values — roadmap §7.4 canonical set
INTENT_INTERESTED = "interested"
INTENT_OBJECTION = "objection"
INTENT_UNSUBSCRIBE = "unsubscribe"
INTENT_QUESTION = "question"
INTENT_NOISE = "noise"

# Map from the existing rule-based intents → the roadmap canonical set.
_RULE_TO_ROADMAP: dict[str, str] = {
    "opt_out": INTENT_UNSUBSCRIBE,
    "not_interested": INTENT_OBJECTION,
    "callback_requested": INTENT_INTERESTED,
    "quote_requested": INTENT_INTERESTED,
    "interested": INTENT_INTERESTED,
    # "neutral" intentionally absent — triggers LLM fallback
}

class _TTLCache:
    """Minimal TTL cache — avoids a cachetools dependency for one helper."""

    def __init__(self, maxsize: int, ttl: int) -> None:
        self._maxsize = maxsize
        self._ttl = ttl
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        expiry, value = entry
        if time.monotonic() >= expiry:
            self._store.pop(key, None)
            return None
        return value

    def __setitem__(self, key: str, value: Any) -> None:
        if len(self._store) >= self._maxsize:
            # Evict the oldest entry by expiry — cheap linear scan at this size.
            oldest_key = min(self._store, key=lambda k: self._store[k][0])
            self._store.pop(oldest_key, None)
        self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        self._store.clear()


# In-process cache — keyed by sha256(body[:500].lower()).
# Small; classifications are short-lived and retries within the TTL are the
# main consumer (webhook deliveries retry on 5xx).
_REPLY_CACHE = _TTLCache(maxsize=512, ttl=3600)

# Very lightweight global LLM budget — we want to avoid hammering Mistral when
# a flurry of inbound replies land at once.  Cycles here are 60s sliding
# windows; after _CYCLE_CAP classifications in a window the classifier falls
# back to the neutral rule result without raising.
_CYCLE_WINDOW_SECONDS = 60
_CYCLE_CAP = 3
_cycle_start: float = 0.0
_cycle_count: int = 0


# Mistral classification prompt
_LLM_SYSTEM_PROMPT = "You classify short inbound sales replies into one of five intents."

_LLM_USER_TEMPLATE = """Classify this inbound message into exactly one of:
- interested — shows positive buying intent, wants to continue the conversation, confirms a next step
- objection — pushes back on price, timing, competitors, or suitability
- unsubscribe — asks to stop being contacted or expresses clear disinterest
- question — asks a factual question about the product, pricing, features, terms, process
- noise — empty, confused, off-topic, or unrelated auto-reply

Return ONLY the single lowercase word from the list above. No punctuation, no explanation.

Channel: {channel}
Message:
\"\"\"
{body}
\"\"\"
"""


def _hash_body(body: str) -> str:
    sample = (body or "").strip().lower()[:500]
    return hashlib.sha256(sample.encode("utf-8", errors="replace")).hexdigest()


def _cycle_ok() -> bool:
    """Return True if we can still run an LLM classification this window."""
    global _cycle_start, _cycle_count
    now = time.monotonic()
    if (now - _cycle_start) > _CYCLE_WINDOW_SECONDS:
        _cycle_start = now
        _cycle_count = 0
    return _cycle_count < _CYCLE_CAP


def _cycle_tick() -> None:
    global _cycle_count
    _cycle_count += 1


def _reset_cycle_for_tests() -> None:
    """Hook for tests — reset the cycle counter + cache."""
    global _cycle_start, _cycle_count
    _cycle_start = 0.0
    _cycle_count = 0
    _REPLY_CACHE.clear()


async def _run_llm_classification(
    session: Session,
    company_id: int,
    body: str,
    channel: str,
) -> str | None:
    """Call Mistral; return one of the 5 intents, or None on any failure.

    Never raises — caller must fall back on None.
    """
    try:
        from credentials_service import get_company_setting_value
        from services.ai.llm import get_llm_service
    except Exception:  # pragma: no cover — import-time failures
        return None

    try:
        mistral_key = get_company_setting_value(session, company_id, "MISTRAL_API_KEY")
    except Exception:
        mistral_key = None

    try:
        llm = get_llm_service("mistral", _LLM_SYSTEM_PROMPT, api_key=mistral_key)
    except Exception as exc:
        logger.warning("[reply_classifier] LLM init failed: %s", exc)
        return None

    prompt = _LLM_USER_TEMPLATE.format(channel=channel or "unknown", body=body[:2000])
    try:
        llm.add_user_message(prompt)
    except Exception as exc:
        logger.warning("[reply_classifier] add_user_message failed: %s", exc)
        return None

    # Small guard: pace after a throttle tick to respect Mistral's free-tier
    # ~1 req/sec.  Other LLM consumers (post-call) use the same cadence.
    await asyncio.sleep(1.2)

    reply_text = ""
    try:
        async for chunk in llm.stream():
            if chunk.get("type") == "finished":
                reply_text = chunk.get("full_reply", reply_text)
                break
            if chunk.get("type") == "token":
                reply_text += chunk.get("content", "")
            if chunk.get("type") == "error":
                logger.warning("[reply_classifier] LLM stream error: %s", chunk.get("content"))
                return None
    except Exception as exc:
        logger.warning("[reply_classifier] LLM stream exception: %s", exc)
        return None

    token = (reply_text or "").strip().lower().split()[:1]
    if not token:
        return None
    intent = token[0].strip(".,!?\"'`()[]")
    valid = {INTENT_INTERESTED, INTENT_OBJECTION, INTENT_UNSUBSCRIBE, INTENT_QUESTION, INTENT_NOISE}
    if intent in valid:
        return intent
    logger.info("[reply_classifier] LLM returned unknown token: %r", reply_text[:120])
    return None


async def classify_reply(
    session: Session,
    company_id: int,
    body: str,
    channel: str,
    lead_id: int | None = None,
) -> dict[str, Any]:
    """Classify an inbound message into one of the roadmap intents.

    Returns {intent, source, confidence} where:
      - intent ∈ {interested, objection, unsubscribe, question, noise}
      - source ∈ {"rule", "llm", "cache", "llm_cap"}
      - confidence is a float 0..1 (heuristic — rule path is 1.0, cache inherits,
        LLM is 0.7, fallback to neutral rule is 0.3)
    """
    rule_label = classify_reply_intent(body)
    if rule_label != "neutral":
        mapped = _RULE_TO_ROADMAP.get(rule_label, INTENT_NOISE)
        return {"intent": mapped, "source": "rule", "confidence": 1.0}

    trimmed = (body or "").strip()
    if len(trimmed) < 10:
        return {"intent": INTENT_NOISE, "source": "rule", "confidence": 1.0}

    # Cache lookup
    key = _hash_body(trimmed)
    cached = _REPLY_CACHE.get(key)
    if cached is not None:
        return {"intent": cached, "source": "cache", "confidence": 0.7}

    # Global budget gate
    if not _cycle_ok():
        logger.info("[reply_classifier] cycle cap reached — falling back to neutral")
        return {"intent": INTENT_NOISE, "source": "llm_cap", "confidence": 0.3}

    _cycle_tick()
    llm_intent = await _run_llm_classification(session, company_id, trimmed, channel)
    if llm_intent is None:
        return {"intent": INTENT_NOISE, "source": "llm", "confidence": 0.3}

    _REPLY_CACHE[key] = llm_intent
    return {"intent": llm_intent, "source": "llm", "confidence": 0.7}


def classify_reply_sync(
    session: Session,
    company_id: int,
    body: str,
    channel: str,
    lead_id: int | None = None,
) -> dict[str, Any]:
    """Sync facade — safe to call from sync webhook handlers.

    If we're already inside an event loop (e.g. FastAPI async handler that
    somehow ended up calling this), we hand the coroutine to a worker thread
    with its own loop.  Mirrors the pattern in automation_worker_service.py.
    """
    coro = classify_reply(session, company_id, body, channel, lead_id)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


async def run(
    company_id: int,
    actor_user_id: int,
    body: str,
    channel: str,
    lead_id: int | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Agent entry point — matches the orchestrator's run_agent convention.

    Usable from AgentTask queue (task_type=\"classify_reply\", assigned_agent=\"reply_classifier\").
    """
    from database import engine as _engine

    with Session(_engine) as session:
        return await classify_reply(session, company_id, body, channel, lead_id)
