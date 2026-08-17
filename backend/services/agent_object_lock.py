"""Agent Object Lock — prevents concurrent agent writes to the same record.

Before any A2/A3 agent touches a record it calls acquire().
After it finishes (success or failure) it calls release().
Locks have a hard TTL so a crashed agent never starves others.

Usage:
    from services.agent_object_lock import acquire_lock, release_lock, LockConflict

    try:
        lock = acquire_lock(session, company_id=1, entity_type="invoice",
                            entity_id=99, agent_name="f1_collections",
                            task_id=task.id, ttl_seconds=300)
    except LockConflict as e:
        # another agent is already working on this record — skip or requeue
        return {"status": "skipped", "reason": str(e)}

    try:
        # ... do the work ...
    finally:
        release_lock(session, lock.id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import Session, select

from models.models import AgentObjectLock, utc_now

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 300  # 5 minutes — enough for any single agent action


class LockConflict(Exception):
    """Raised when the requested lock is already held by another agent."""


def acquire_lock(
    session: Session,
    company_id: int,
    entity_type: str,
    entity_id: int,
    agent_name: str,
    task_id: Optional[int] = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> AgentObjectLock:
    """Acquire the lock or raise LockConflict.

    Expired locks are silently swept before the check so a crashed agent
    does not permanently block others.
    """
    now = datetime.now(timezone.utc)

    # Sweep any expired lock on this entity first
    existing = session.exec(
        select(AgentObjectLock).where(
            AgentObjectLock.company_id == company_id,
            AgentObjectLock.entity_type == entity_type,
            AgentObjectLock.entity_id == entity_id,
        )
    ).first()

    if existing:
        if existing.expires_at <= now:
            # Lock is stale — delete it and proceed
            session.delete(existing)
            session.flush()
        else:
            raise LockConflict(
                f"entity {entity_type}:{entity_id} is locked by '{existing.locked_by_agent}' "
                f"(task_id={existing.locked_by_task_id}) until {existing.expires_at.isoformat()}"
            )

    lock = AgentObjectLock(
        company_id=company_id,
        entity_type=entity_type,
        entity_id=entity_id,
        locked_by_agent=agent_name,
        locked_by_task_id=task_id,
        acquired_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    session.add(lock)
    session.flush()
    logger.debug(
        "[object_lock] acquired %s:%d by %s (ttl=%ds)",
        entity_type, entity_id, agent_name, ttl_seconds,
    )
    return lock


def release_lock(session: Session, lock_id: int) -> None:
    """Release a previously acquired lock. Safe to call even if already gone."""
    lock = session.get(AgentObjectLock, lock_id)
    if lock:
        session.delete(lock)
        session.flush()
        logger.debug("[object_lock] released lock id=%d", lock_id)


def sweep_expired_locks(session: Session) -> int:
    """Delete all expired locks across all companies. Call from the automation worker."""
    now = datetime.now(timezone.utc)
    expired = session.exec(
        select(AgentObjectLock).where(AgentObjectLock.expires_at <= now)
    ).all()
    for lock in expired:
        session.delete(lock)
    if expired:
        session.flush()
        logger.info("[object_lock] swept %d expired locks", len(expired))
    return len(expired)
