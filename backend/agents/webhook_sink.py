"""Webhook sink agent — no-op executor for webhook-audit AgentTasks.

Phase 1 of the webhook-migration pattern (Week 2.3): this agent completes
every webhook_audit task without doing real work. Its only purpose is to
clear the pending queue so operators see `status=done` rather than a
growing backlog of "pending" audit rows.

Phase 2 (Week 3+): replace this no-op with real handlers per event_type —
call-outcome processing, lead state advancement on quote_accept, etc.
Because audit rows already carry the full payload, Phase 2 can read from
AgentTask.input_json["payload"] without any webhook handler changes.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run(
    *,
    company_id: int,
    actor_user_id: int = 0,
    lead_id: int | None = None,
    task_type: str | None = None,
    event_type: str | None = None,
    provider_event_id: str | None = None,
    extra: str = "",
    payload: dict | None = None,
    **_unused: Any,
) -> dict:
    """No-op handler — just acknowledge the audit and return.

    Returning a dict with ok=True tells the worker to mark the task `done`.
    Phase 2 will replace this with real event-type dispatch.
    """
    logger.debug(
        "[webhook_sink] audited event_type=%s provider_event_id=%s extra=%s lead=%s",
        event_type, provider_event_id, extra, lead_id,
    )
    return {
        "ok": True,
        "sink": "noop",
        "event_type": event_type,
        "provider_event_id": provider_event_id,
    }
