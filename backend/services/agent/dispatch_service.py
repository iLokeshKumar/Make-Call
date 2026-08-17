"""Enqueue helpers for routing external send actions through the AgentTask queue.

Production callers (ISM orchestrator, campaign step executor, post-call flows,
manual user actions) should invoke these instead of calling the communication
service directly. They:

1. Build a stable idempotency_key so duplicate triggers dedupe at the DB.
2. Tag the task with `assigned_agent="send"` so the worker routes it to the
   send executor (agents/send.py).
3. Populate the input_json payload the executor needs.

Feature flag: USE_AGENT_TASK_QUEUE (default "1"). Set "0" to fall back to
synchronous direct dispatch — a one-line rollback for the Week 2 migration.

Live-call critical path (voice pipeline) should NOT use these helpers — the
per-turn latency of enqueue + worker claim + execute blows the ~800ms budget.
That path calls communication_service directly and stays synchronous.
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)


def _queue_enabled() -> bool:
    """Respect USE_AGENT_TASK_QUEUE env var. Defaults to enabled."""
    return os.getenv("USE_AGENT_TASK_QUEUE", "1") == "1"


def _build_idempotency_key(task_type: str, lead_id: int, trigger: str, discriminator: str = "") -> str:
    """Build a stable key fingerprint that fits AgentTask.idempotency_key (VARCHAR(200)).

    trigger = short label of WHY we're sending ("ism_stage:engaged",
              "campaign:welcome_step_2", "manual", "post_call_nurture").
    discriminator = anything that makes otherwise-identical triggers unique
                    (subject for emails, message content for whatsapp, etc.).
    """
    raw = f"{task_type}|{lead_id}|{trigger}|{discriminator}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
    return f"{task_type}:{lead_id}:{digest}"


def enqueue_send_email(
    session: Session,
    *,
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    subject: str,
    body: str,
    cta_url: str = "",
    cta_label: str = "",
    trigger: str = "manual",
    requires_approval: Optional[bool] = None,
) -> Any:
    """Enqueue a send_email task, or dispatch synchronously if queue is off.

    Returns the created AgentTask (queue path) or the send_email_to_lead
    result dict (synchronous path).
    """
    if not _queue_enabled():
        from services.communication.communication_service import send_email_to_lead
        logger.debug("[dispatch] queue disabled — sending email synchronously")
        return send_email_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            subject=subject,
            body=body,
            cta_url=cta_url,
            cta_label=cta_label,
        )

    from services.agent.agent_task_service import create_agent_task
    key = _build_idempotency_key("send_email", lead_id, trigger, subject)
    summary = f"Send email to lead {lead_id}: {subject[:80]}"
    return create_agent_task(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        task_type="send_email",
        assigned_agent="send",
        input_json={
            "task_type": "send_email",
            "subject": subject,
            "body": body,
            "cta_url": cta_url,
            "cta_label": cta_label,
            "summary": summary,
        },
        idempotency_key=key,
        requires_approval=requires_approval,
        actor_user_id=actor_user_id,
    )


def enqueue_send_whatsapp(
    session: Session,
    *,
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    body: str,
    trigger: str = "manual",
    requires_approval: Optional[bool] = None,
) -> Any:
    """Enqueue a send_whatsapp task, or dispatch synchronously if queue is off."""
    if not _queue_enabled():
        from services.communication.communication_service import send_whatsapp_to_lead
        logger.debug("[dispatch] queue disabled — sending whatsapp synchronously")
        return send_whatsapp_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            body=body,
        )

    from services.agent.agent_task_service import create_agent_task
    # First 80 chars of body = stable-enough discriminator without leaking full msg into key
    key = _build_idempotency_key("send_whatsapp", lead_id, trigger, body[:80])
    summary = f"Send WhatsApp to lead {lead_id}: {body[:80]}"
    return create_agent_task(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        task_type="send_whatsapp",
        assigned_agent="send",
        input_json={
            "task_type": "send_whatsapp",
            "body": body,
            "summary": summary,
        },
        idempotency_key=key,
        requires_approval=requires_approval,
        actor_user_id=actor_user_id,
    )


def enqueue_send_quote(
    session: Session,
    *,
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    quote_id: int,
    channels: list[str],
    subject: Optional[str] = None,
    message: Optional[str] = None,
    trigger: str = "manual",
    requires_approval: Optional[bool] = None,
) -> Any:
    """Enqueue a send_quote task, or dispatch synchronously if queue is off.

    `channels` is required (list of "email", "whatsapp"). The actual quote is
    looked up by quote_id in the executor, not embedded in input_json, so the
    payload stays small.
    """
    if not _queue_enabled():
        from services.communication.communication_service import send_quote_to_lead
        logger.debug("[dispatch] queue disabled — sending quote synchronously")
        return send_quote_to_lead(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            quote_id=quote_id,
            channels=channels,
            subject=subject,
            message=message,
        )

    from services.agent.agent_task_service import create_agent_task
    key = _build_idempotency_key("send_quote", lead_id, trigger, f"q{quote_id}")
    summary = f"Send quote #{quote_id} to lead {lead_id} via {','.join(channels)}"
    return create_agent_task(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        task_type="send_quote",
        assigned_agent="send",
        input_json={
            "task_type": "send_quote",
            "quote_id": quote_id,
            "channels": channels,
            "subject": subject or "",
            "message": message,
            "summary": summary,
        },
        idempotency_key=key,
        requires_approval=requires_approval,
        actor_user_id=actor_user_id,
    )
