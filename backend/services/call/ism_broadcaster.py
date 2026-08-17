"""
Real-time ISM activity broadcaster — Postgres-backed pub/sub.

Mirrors `call_status_broadcaster` and `sentiment_broadcaster`: events are
written to the `ism_activity_events` table so they're visible across all
uvicorn workers.  The WebSocket handler at `/ws/ism-activity/{company_id}`
polls every 500ms with a cursor.

Usage:
    from services.call import ism_broadcaster
    ism_broadcaster.publish(
        company_id=1,
        lead_id=42,
        lead_name="Priya at TechCorp",
        stage="contacted",
        action="dispatched_email",
        reason="lead replied to email campaign",
        metadata={"channel": "email", "interaction_id": 198},
    )
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def publish(
    *,
    company_id: int,
    lead_id: Optional[int],
    lead_name: Optional[str],
    stage: Optional[str],
    action: str,
    reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> None:
    """Write an ISM activity event.  Silent on DB error — never break the
    decision path because of an observability write.
    """
    try:
        from database import engine as _engine
        from sqlmodel import Session as _Session
        from models.models import IsmActivityEvent

        with _Session(_engine) as s:
            s.add(IsmActivityEvent(
                company_id=company_id,
                lead_id=lead_id,
                lead_name=lead_name,
                stage=stage,
                action=action,
                reason=(reason or "")[:400] or None,
                metadata_json=metadata or None,
            ))
            s.commit()
    except Exception as exc:  # noqa: BLE001
        logger.debug("IsmActivityEvent DB write skipped: %s", exc)
