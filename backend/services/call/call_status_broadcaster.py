"""
Real-time call-status broadcaster — PostgreSQL-backed pub/sub.

Events are written to the `call_status_events` table so they are visible
to all uvicorn workers.  The WebSocket handler polls the table every 500ms
using a cursor (last_id), identical to the sentiment_broadcaster pattern.

Usage:
    from services import call_status_broadcaster
    call_status_broadcaster.publish(
        company_id=1,
        campaign_id=5,          # None for ad-hoc calls
        call_task_id=12,
        interaction_id="42",
        lead_id=7,
        lead_name="Ramesh Kumar",
        status="ringing",       # pre-call: "queued" | "scheduled" | "prepared" | "initiated" | "ringing"
                                # active:   "in_progress" | "connected"
                                # terminal: "ended"
        outcome=None,           # set only on "ended": "completed" | "failed" | "busy" | "no_answer"
                                #   | "cancelled" | "error" | "low_balance" | "stopped"
    )
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def publish(
    *,
    company_id: int,
    campaign_id: int | None,
    call_task_id: int | None,
    interaction_id: str | None,
    lead_id: int | None,
    lead_name: str | None,
    status: str,
    outcome: str | None = None,
) -> None:
    """Write a call-status event to PostgreSQL.

    Works across all uvicorn workers — no shared in-process state.
    Silently swallows DB errors so it never disrupts the call path.
    """
    try:
        from database import engine as _engine
        from sqlmodel import Session as _Session
        from models.models import CallStatusEvent

        with _Session(_engine) as s:
            s.add(CallStatusEvent(
                company_id=company_id,
                campaign_id=campaign_id,
                call_task_id=call_task_id,
                interaction_id=str(interaction_id) if interaction_id is not None else None,
                lead_id=lead_id,
                lead_name=lead_name,
                status=status,
                outcome=outcome,
            ))
            s.commit()
    except Exception as exc:
        logger.debug("CallStatusEvent DB write skipped: %s", exc)
