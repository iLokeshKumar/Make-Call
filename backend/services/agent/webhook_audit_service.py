"""Webhook audit — durable record of every external event the app receives.

Pattern: webhook handlers call `enqueue_webhook_audit(...)` in addition to
their inline work. That creates an AgentTask with a deterministic
`idempotency_key` derived from the provider's event ID. Carrier retries
dedupe at the DB; the app owns a durable record of every event regardless
of how well the inline handler ran.

Phase 1 (Week 2.3 — this module): audit is purely additive. Inline handler
logic stays. The `webhook_sink` agent is a no-op executor that just marks
the task complete.

Phase 2 (Week 3): migrate the heavy inline work (call-outcome processing,
quote state mutations, interaction-delivery tracking) out of the route
handler and into real executors. The audit key + payload already exist;
Phase 2 only moves the work, not the data.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)

_AUDIT_TASK_TYPE = "webhook_audit"
_AUDIT_AGENT = "webhook_sink"


def _make_audit_key(event_type: str, provider_event_id: str, extra: str = "") -> str:
    """Compose a stable, unique key under the 200-char column limit.

    Raw inputs can be long (Twilio SIDs, email Message-Ids) so we hash the
    combination and include a bounded-length event_type prefix for log
    readability. Event types longer than 40 chars get truncated in the
    visible prefix (but the hash still uses the full value — no collisions).
    """
    raw = f"{event_type}|{provider_event_id}|{extra}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    visible_event_type = event_type[:40]
    return f"webhook:{visible_event_type}:{digest}"


def enqueue_webhook_audit(
    session: Session,
    *,
    company_id: int,
    event_type: str,
    provider_event_id: str,
    payload: dict[str, Any],
    lead_id: Optional[int] = None,
    extra: str = "",
    actor_user_id: Optional[int] = None,
) -> Any:
    """Create or dedupe an audit AgentTask for an incoming webhook event.

    Fire-and-forget semantics: this is safe to call before or after the
    inline handler work. Never raises — returns None on any internal error
    so a webhook can't fail on audit trouble. The webhook's real response
    is produced by its own handler code, not by this function.

    event_type examples: "twilio_call_status", "twilio_whatsapp_inbound",
                         "twilio_whatsapp_status", "email_inbound",
                         "quote_accept", "quote_reject"

    provider_event_id: a string the provider guarantees is unique per event
                       — CallSid, MessageSid, Message-Id header, etc.

    extra: disambiguator when the provider_event_id alone isn't unique for
           the event you're auditing. Example: Twilio sends multiple status
           callbacks per CallSid (ringing, in-progress, completed) — pass
           CallStatus as `extra` so each gets its own audit row.
    """
    try:
        from services.agent.agent_task_service import create_agent_task
        key = _make_audit_key(event_type, provider_event_id, extra)
        task = create_agent_task(
            session=session,
            company_id=company_id,
            lead_id=lead_id,
            task_type=_AUDIT_TASK_TYPE,
            assigned_agent=_AUDIT_AGENT,
            input_json={
                "task_type": _AUDIT_TASK_TYPE,
                "event_type": event_type,
                "provider_event_id": provider_event_id,
                "extra": extra,
                "payload": payload,
                "summary": f"Webhook audit: {event_type} / {provider_event_id[:64]}",
            },
            idempotency_key=key,
            requires_approval=False,       # audits never need human approval
            actor_user_id=actor_user_id,
        )
        return task
    except Exception as exc:  # noqa: BLE001
        # Webhook handlers MUST NOT fail on audit trouble. Log and continue.
        logger.warning(
            "[webhook_audit] enqueue failed for event_type=%s: %s",
            event_type, exc,
        )
        return None
