from __future__ import annotations

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import Lead, OptOut, utc_now
from services.leads.engagement_service import record_engagement_event


def is_lead_opted_out(session: Session, company_id: int, lead_id: int, channel: str) -> bool:
    existing = session.exec(
        select(OptOut).where(
            OptOut.company_id == company_id,
            OptOut.lead_id == lead_id,
            OptOut.channel == channel,
        )
    ).first()
    return existing is not None


def unsubscribe_lead(
    session: Session,
    company_id: int,
    actor_user_id: int | None,
    lead_id: int,
    channel: str,
    reason: str | None = None,
) -> OptOut:
    lead = session.exec(
        select(Lead).where(
            Lead.id == lead_id,
            Lead.company_id == company_id,
        )
    ).first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    existing = session.exec(
        select(OptOut).where(
            OptOut.company_id == company_id,
            OptOut.lead_id == lead_id,
            OptOut.channel == channel,
        )
    ).first()
    if existing:
        return existing

    opt_out = OptOut(
        company_id=company_id,
        lead_id=lead_id,
        channel=channel,
        reason=reason,
    )
    session.add(opt_out)
    lead.updated_at = utc_now()
    if actor_user_id is not None:
        lead.updated_by = actor_user_id
    session.add(lead)
    session.commit()
    session.refresh(opt_out)
    record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=None,
        quote_id=None,
        channel=channel,
        event_type="unsubscribe",
        payload={"reason": reason},
    )
    return opt_out
