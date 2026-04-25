from __future__ import annotations

import asyncio
import logging
import os
from datetime import timedelta

from sqlmodel import Session, select

from credentials_service import get_email_credential
from database import engine
from email_service import send_smtp_email
from models.models import EmailOutbox, utc_now

logger = logging.getLogger(__name__)

DEFAULT_MAX_ATTEMPTS = 5
DEFAULT_BATCH_SIZE = 25
DEFAULT_POLL_SECONDS = 15
BACKOFF_MINUTES = [1, 5, 15, 30, 60]


def enqueue_email(
    session: Session,
    *,
    company_id: int,
    actor_user_id: int | None,
    to_email: str,
    subject: str,
    body: str,
    html_body: str | None,
    company_name: str | None = None,
    feedback_id: int | None = None,
    dedupe_key: str | None = None,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> EmailOutbox:
    if dedupe_key:
        existing = session.exec(
            select(EmailOutbox).where(EmailOutbox.dedupe_key == dedupe_key)
        ).first()
        if existing and existing.status != "failed":
            return existing

    # Capture the current request_id (or worker trace_id) so the outbound
    # mail row can be correlated back to the request that queued it.
    try:
        from utils.logger import request_id_var
        _rid = request_id_var.get("-")
        request_id_value = _rid if _rid and _rid != "-" else None
    except Exception:  # noqa: BLE001
        request_id_value = None

    item = EmailOutbox(
        company_id=company_id,
        actor_user_id=actor_user_id,
        feedback_id=feedback_id,
        dedupe_key=dedupe_key,
        to_email=to_email,
        subject=subject,
        body=body,
        html_body=html_body,
        company_name=company_name,
        status="pending",
        attempts=0,
        max_attempts=max_attempts,
        next_attempt_at=utc_now(),
        request_id=request_id_value,
        created_by=actor_user_id,
        updated_by=actor_user_id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)
    return item


def _next_backoff_minutes(attempt_number: int) -> int:
    idx = max(0, min(attempt_number - 1, len(BACKOFF_MINUTES) - 1))
    return BACKOFF_MINUTES[idx]


def process_outbox_batch(
    session: Session,
    *,
    company_id: int | None = None,
    limit: int = DEFAULT_BATCH_SIZE,
) -> dict[str, int]:
    now = utc_now()
    query = select(EmailOutbox).where(
        EmailOutbox.status == "pending",
        EmailOutbox.next_attempt_at <= now,
        EmailOutbox.attempts < EmailOutbox.max_attempts,
    )
    if company_id is not None:
        query = query.where(EmailOutbox.company_id == company_id)

    items = session.exec(
        query.order_by(EmailOutbox.next_attempt_at.asc()).limit(limit)
    ).all()

    sent = 0
    failed = 0
    retried = 0

    for item in items:
        actor_id = item.actor_user_id or item.created_by
        if not actor_id:
            item.attempts += 1
            item.last_issue = "Missing actor_user_id for SMTP credential lookup"
            if item.attempts >= item.max_attempts:
                item.status = "failed"
                failed += 1
            else:
                item.next_attempt_at = now + timedelta(minutes=_next_backoff_minutes(item.attempts))
                retried += 1
            item.updated_at = utc_now()
            session.add(item)
            session.commit()
            continue

        smtp_kwargs = dict(
            smtp_host=get_email_credential(session, item.company_id, actor_id, "SMTP_HOST"),
            smtp_port=get_email_credential(session, item.company_id, actor_id, "SMTP_PORT"),
            smtp_security=get_email_credential(session, item.company_id, actor_id, "SMTP_SECURITY"),
            smtp_username=get_email_credential(session, item.company_id, actor_id, "SMTP_USERNAME"),
            smtp_password=get_email_credential(session, item.company_id, actor_id, "SMTP_PASSWORD"),
            smtp_from_email=get_email_credential(session, item.company_id, actor_id, "SMTP_FROM_EMAIL"),
        )

        try:
            send_smtp_email(
                to_email=item.to_email,
                subject=item.subject,
                body=item.body,
                html_body=item.html_body,
                company_name=item.company_name or "Rio CRM",
                **smtp_kwargs,
            )
            item.status = "sent"
            item.sent_at = utc_now()
            item.updated_at = utc_now()
            session.add(item)
            session.commit()
            sent += 1
        except Exception as exc:  # noqa: BLE001
            item.attempts += 1
            item.last_issue = str(exc)[:2000]
            item.updated_at = utc_now()
            if item.attempts >= item.max_attempts:
                item.status = "failed"
                failed += 1
            else:
                item.next_attempt_at = now + timedelta(minutes=_next_backoff_minutes(item.attempts))
                retried += 1
            session.add(item)
            session.commit()
            logger.warning(
                "[EmailOutbox] send failed id=%s attempt=%s/%s error=%s",
                item.id,
                item.attempts,
                item.max_attempts,
                item.last_issue,
            )

    return {"processed": len(items), "sent": sent, "retried": retried, "failed": failed}


def _process_once_sync() -> None:
    with Session(engine) as session:
        result = process_outbox_batch(session)
        if result["processed"] > 0:
            logger.info("[EmailOutbox] cycle=%s", result)


async def email_outbox_loop() -> None:
    poll_seconds_raw = os.getenv("EMAIL_OUTBOX_POLL_SECONDS")
    try:
        poll_seconds = max(2, int(poll_seconds_raw or DEFAULT_POLL_SECONDS))
    except Exception:
        poll_seconds = DEFAULT_POLL_SECONDS

    while True:
        try:
            await asyncio.to_thread(_process_once_sync)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[EmailOutbox] loop error: %s", exc)
        await asyncio.sleep(poll_seconds)
