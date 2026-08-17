"""
Event Store Service — immutable append-only domain event log.

Every significant state change in the system (lead stage change, quote acceptance,
order confirmation, payment capture, etc.) should emit an event here via emit().

Events are never updated or deleted. They can be queried by aggregate or by
correlation_id to reconstruct causality chains.

Correlation IDs tie together all events that originated from the same user action
(e.g. "user accepted quote" → order.confirmed + invoice.created + event.sent all
share the same correlation_id).

Causation IDs record which event triggered this one, enabling a directed event graph.
"""
from __future__ import annotations

import logging
import uuid

from sqlmodel import Session, select

from models.models import EventStore, utc_now

logger = logging.getLogger(__name__)


def emit(
    session: Session,
    company_id: int,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    payload: dict,
    actor_user_id: int | None = None,
    actor_agent: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
) -> EventStore:
    """
    Append an immutable event to the event store.

    Parameters
    ----------
    event_type     : Domain event identifier, e.g. "lead.stage_changed",
                     "quote.accepted", "order.confirmed", "invoice.sent".
    aggregate_type : High-level domain object type: lead | quote | order |
                     invoice | ticket | payment | install.
    aggregate_id   : Primary key of the aggregate.
    payload        : Arbitrary event data dict (serialised as JSON).
    actor_user_id  : User who initiated the action (None for system events).
    actor_agent    : Agent identifier when triggered by an AI agent.
    correlation_id : Ties events from the same user action together. If not
                     provided a new UUID4 is generated.
    causation_id   : ID (correlation_id or event id) of the event that caused
                     this one.

    Returns
    -------
    The persisted EventStore record.
    """
    if not correlation_id:
        correlation_id = uuid.uuid4().hex

    # Compute per-aggregate version number (next in sequence)
    existing_count = session.exec(
        select(EventStore).where(
            EventStore.aggregate_type == aggregate_type,
            EventStore.aggregate_id == aggregate_id,
        )
    ).all()
    version = len(existing_count) + 1

    event = EventStore(
        company_id=company_id,
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        version=version,
        payload=payload or {},
        actor_user_id=actor_user_id,
        actor_agent=actor_agent,
        created_at=utc_now(),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    logger.debug(
        "[EventStore] Emitted event_type=%s aggregate=%s:%s correlation=%s v=%s",
        event_type, aggregate_type, aggregate_id, correlation_id, version,
    )
    return event


def get_events(
    session: Session,
    company_id: int,
    aggregate_type: str,
    aggregate_id: int,
) -> list[EventStore]:
    """
    Return all events for a specific aggregate, ordered by created_at ascending.

    Parameters
    ----------
    aggregate_type : E.g. "lead", "quote", "order".
    aggregate_id   : Primary key of the aggregate.
    """
    return session.exec(
        select(EventStore).where(
            EventStore.company_id == company_id,
            EventStore.aggregate_type == aggregate_type,
            EventStore.aggregate_id == aggregate_id,
        ).order_by(EventStore.created_at.asc())
    ).all()


def get_events_by_correlation(
    session: Session,
    company_id: int,
    correlation_id: str,
) -> list[EventStore]:
    """
    Return all events sharing a given correlation_id, ordered by created_at ascending.

    Useful for reconstructing everything that happened as part of one user action.
    """
    return session.exec(
        select(EventStore).where(
            EventStore.company_id == company_id,
            EventStore.correlation_id == correlation_id,
        ).order_by(EventStore.created_at.asc())
    ).all()
