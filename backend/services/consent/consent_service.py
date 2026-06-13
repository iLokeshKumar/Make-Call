"""
Consent Service — per-lead per-channel consent management.

Tracks whether a lead has granted consent for a given communication
channel (call, email, whatsapp, sms). All outbound communication
services should call has_consent() or require_consent() before sending.

Consent lifecycle:
  pending → granted → revoked | expired
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import ConsentRecord, utc_now

logger = logging.getLogger(__name__)


def get_consent(
    session: Session,
    company_id: int,
    lead_id: int,
    channel: str,
) -> ConsentRecord | None:
    """Return the ConsentRecord for a given company/lead/channel, or None."""
    return session.exec(
        select(ConsentRecord).where(
            ConsentRecord.company_id == company_id,
            ConsentRecord.lead_id == lead_id,
            ConsentRecord.channel == channel,
        )
    ).first()


def has_consent(
    session: Session,
    company_id: int,
    lead_id: int,
    channel: str,
) -> bool:
    """
    Return True only if the lead has an active granted consent for this channel.
    A consent is active when status="granted" and either expires_at is None
    or expires_at is in the future.
    """
    record = get_consent(session, company_id, lead_id, channel)
    if record is None:
        return False
    if record.status != "granted":
        return False
    if record.expires_at is not None and record.expires_at <= utc_now():
        return False
    return True


def grant_consent(
    session: Session,
    company_id: int,
    lead_id: int,
    channel: str,
    source: str = "explicit",
    interaction_id: int | None = None,
    expires_days: int | None = None,
) -> ConsentRecord:
    """
    Grant consent for a channel. If a ConsentRecord already exists it is
    updated in-place; otherwise a new record is created.

    Parameters
    ----------
    expires_days : If provided, the consent expires after this many days from now.
                   None = no expiry.
    """
    now = utc_now()
    expires_at: datetime | None = None
    if expires_days is not None:
        expires_at = now + timedelta(days=expires_days)

    record = get_consent(session, company_id, lead_id, channel)
    if record is None:
        record = ConsentRecord(
            company_id=company_id,
            lead_id=lead_id,
            channel=channel,
            status="granted",
            granted_at=now,
            revoked_at=None,
            expires_at=expires_at,
            source=source,
            source_interaction_id=interaction_id,
            updated_at=now,
        )
    else:
        record.status = "granted"
        record.granted_at = now
        record.revoked_at = None
        record.expires_at = expires_at
        record.source = source
        record.source_interaction_id = interaction_id
        record.updated_at = now

    session.add(record)
    session.commit()
    session.refresh(record)
    logger.info(
        "[ConsentService] Granted consent: company=%s lead=%s channel=%s source=%s",
        company_id, lead_id, channel, source,
    )
    return record


def revoke_consent(
    session: Session,
    company_id: int,
    lead_id: int,
    channel: str,
    notes: str | None = None,
) -> ConsentRecord:
    """
    Revoke consent for a channel. Raises 404 if no record exists.
    """
    record = get_consent(session, company_id, lead_id, channel)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"No consent record found for lead {lead_id} channel {channel}",
        )

    now = utc_now()
    record.status = "revoked"
    record.revoked_at = now
    record.updated_at = now
    if notes is not None:
        record.notes = notes

    session.add(record)
    session.commit()
    session.refresh(record)
    logger.info(
        "[ConsentService] Revoked consent: company=%s lead=%s channel=%s",
        company_id, lead_id, channel,
    )
    return record


def require_consent(
    session: Session,
    company_id: int,
    lead_id: int,
    channel: str,
) -> None:
    """
    Assert that valid consent exists. Raises HTTP 403 if not.

    Intended to be called at the start of any outbound communication flow.
    """
    if not has_consent(session, company_id, lead_id, channel):
        raise HTTPException(
            status_code=403,
            detail=f"No consent for {channel} communication with lead {lead_id}",
        )


def list_consents(
    session: Session,
    company_id: int,
    lead_id: int,
) -> list[ConsentRecord]:
    """Return all ConsentRecords for a lead, regardless of status."""
    return session.exec(
        select(ConsentRecord).where(
            ConsentRecord.company_id == company_id,
            ConsentRecord.lead_id == lead_id,
        ).order_by(ConsentRecord.channel.asc())
    ).all()
