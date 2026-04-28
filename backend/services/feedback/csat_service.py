from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from models.models import Feedback
from utils.url_utils import normalize_base_url

DEFAULT_CSAT_EXPIRY_HOURS = 72
DEFAULT_CSAT_DEDUPE_WINDOW_HOURS = 24


def get_csat_base_url() -> str:
    return normalize_base_url(
        os.getenv("FRONTEND_BASE_URL") or os.getenv("DOMAIN"),
        "https://localhost:3000",
    )


def get_csat_dedupe_window_hours() -> int:
    raw = os.getenv("CSAT_DEDUPE_WINDOW_HOURS")
    if not raw:
        return DEFAULT_CSAT_DEDUPE_WINDOW_HOURS
    try:
        return max(1, int(raw))
    except Exception:
        return DEFAULT_CSAT_DEDUPE_WINDOW_HOURS


def get_or_create_pending_csat(
    session: Session,
    *,
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    interaction_id: int | None,
    expires_hours: int = DEFAULT_CSAT_EXPIRY_HOURS,
    dedupe_window_hours: int | None = None,
) -> tuple[Feedback, bool]:
    now = datetime.now(timezone.utc)
    window_hours = dedupe_window_hours or get_csat_dedupe_window_hours()
    window_start = now - timedelta(hours=window_hours)

    base_filters = [
        Feedback.company_id == company_id,
        Feedback.lead_id == lead_id,
        Feedback.feedback_type == "csat",
        Feedback.source == "customer",
        Feedback.status == "pending",
        Feedback.token.isnot(None),
        Feedback.token_expires_at.isnot(None),
        Feedback.token_expires_at > now,
        Feedback.created_at >= window_start,
    ]
    if interaction_id is not None:
        base_filters.append(Feedback.interaction_id == interaction_id)
    pending = session.exec(
        select(Feedback).where(*base_filters).order_by(Feedback.created_at.desc())
    ).first()
    if pending:
        return pending, False

    expires_at = now + timedelta(hours=max(1, expires_hours))
    fb = Feedback(
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        submitted_by_user_id=actor_user_id,
        feedback_type="csat",
        source="customer",
        token=secrets.token_urlsafe(32),
        token_expires_at=expires_at,
        status="pending",
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(fb)
    session.commit()
    session.refresh(fb)
    return fb, True
