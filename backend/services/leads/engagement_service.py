"""
Engagement event recording — writes EngagementEvent rows and updates
related Interaction/Quote timestamps. No cross-service imports.
"""
from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from models.models import EngagementEvent, Interaction, Lead, Quote, utc_now


def record_engagement_event(
    session: Session,
    company_id: int,
    lead_id: int | None,
    interaction_id: int | None,
    quote_id: int | None,
    channel: str | None,
    event_type: str,
    payload: dict | None = None,
) -> EngagementEvent:
    event = EngagementEvent(
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        quote_id=quote_id,
        channel=channel,
        event_type=event_type,
        payload=payload,
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def record_email_sent(
    session: Session,
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    interaction_id: int,
    tracking_payload: dict | None = None,
) -> dict[str, Any]:
    interaction = session.get(Interaction, interaction_id)
    if not interaction or interaction.company_id != company_id:
        raise HTTPException(status_code=404, detail="Interaction not found")

    metadata = interaction.metadata_json or {}
    metadata.update(tracking_payload or {})
    interaction.metadata_json = metadata
    interaction.delivery_status = "sent"
    interaction.status = "completed"
    interaction.updated_at = utc_now()
    interaction.updated_by = actor_user_id
    session.add(interaction)
    session.commit()

    event = record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        quote_id=None,
        channel="email",
        event_type="sent",
        payload=tracking_payload or {},
    )
    return {"interaction_id": interaction_id, "event_id": event.id}


def _get_interaction_by_token(session: Session, token: str) -> Interaction | None:
    interactions = session.exec(select(Interaction).where(Interaction.channel == "email")).all()
    for interaction in interactions:
        metadata = interaction.metadata_json or {}
        if metadata.get("tracking_token") == token:
            return interaction
    return None


def record_email_open(session: Session, token: str) -> dict[str, Any]:
    interaction = _get_interaction_by_token(session, token)
    if not interaction:
        raise HTTPException(status_code=404, detail="Tracking token not found")

    metadata = dict(interaction.metadata_json or {})
    metadata["opened_at"] = utc_now().isoformat()
    interaction.metadata_json = metadata
    interaction.updated_at = utc_now()
    session.add(interaction)
    session.commit()

    event = record_engagement_event(
        session=session,
        company_id=interaction.company_id,
        lead_id=interaction.lead_id,
        interaction_id=interaction.id,
        quote_id=None,
        channel="email",
        event_type="open",
        payload={"tracking_token": token},
    )
    return {"interaction_id": interaction.id, "event_id": event.id}


def record_email_click(session: Session, token: str, target_url: str) -> dict[str, Any]:
    interaction = _get_interaction_by_token(session, token)
    if not interaction:
        raise HTTPException(status_code=404, detail="Tracking token not found")

    event = record_engagement_event(
        session=session,
        company_id=interaction.company_id,
        lead_id=interaction.lead_id,
        interaction_id=interaction.id,
        quote_id=None,
        channel="email",
        event_type="click",
        payload={"tracking_token": token, "target_url": target_url},
    )
    return {"interaction_id": interaction.id, "event_id": event.id, "target_url": target_url}


def record_whatsapp_event(
    session: Session,
    company_id: int,
    interaction_id: int | None,
    event_type: str,
    payload: dict | None,
) -> dict[str, Any]:
    lead_id = None
    if interaction_id is not None:
        interaction = session.get(Interaction, interaction_id)
        if interaction and interaction.company_id == company_id:
            lead_id = interaction.lead_id
            metadata = interaction.metadata_json or {}
            metadata.setdefault("whatsapp_events", []).append({"event_type": event_type, "payload": payload or {}})
            interaction.metadata_json = metadata
            interaction.updated_at = utc_now()
            session.add(interaction)
            session.commit()

    event = record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=lead_id,
        interaction_id=interaction_id,
        quote_id=None,
        channel="whatsapp",
        event_type=event_type,
        payload=payload or {},
    )
    return {"event_id": event.id}


def record_quote_event(
    session: Session,
    company_id: int,
    quote_id: int,
    event_type: str,
    payload: dict | None = None,
) -> dict[str, Any]:
    quote = session.exec(
        select(Quote).where(
            Quote.id == quote_id,
            Quote.company_id == company_id,
            Quote.deleted_at.is_(None),
        )
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    now = utc_now()
    quote_opened_first_time = False
    if event_type == "opened" and quote.opened_at is None:
        quote.opened_at = now
        quote_opened_first_time = True
    elif event_type == "sent" and quote.sent_at is None:
        quote.sent_at = now
    elif event_type == "accepted":
        quote.accepted_at = now
        quote.status = "accepted"
    elif event_type == "rejected":
        quote.rejected_at = now
        quote.status = "rejected"

    session.add(quote)
    session.commit()

    event = record_engagement_event(
        session=session,
        company_id=company_id,
        lead_id=quote.lead_id,
        interaction_id=None,
        quote_id=quote.id,
        channel="quote",
        event_type=event_type,
        payload=payload or {},
    )

    if quote_opened_first_time:
        lead = session.get(Lead, quote.lead_id)
        if lead:
            lead.next_action = "quote_opened"
            lead.next_action_due_at = now
            lead.updated_at = now
            session.add(lead)
            session.commit()

    return {"quote_id": quote.id, "event_id": event.id, "automation_triggered": quote_opened_first_time}
