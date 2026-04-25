"""Postgres LISTEN/NOTIFY helper for waking the automation worker.

When a new AgentTask is enqueued, we fire `pg_notify('agent_task_ready', '<company_id>')`
inside the same transaction as the row insert. The worker maintains a long-lived
raw connection that LISTENs on this channel and uses `select.select()` to wake on
either an incoming notification or a poll-tick timeout.

Reaction time goes from "up to poll_interval seconds" to "sub-second when notified",
while the polling tick stays as a safety net for missed notifications (e.g. the
worker was disconnected when NOTIFY fired).

If the engine isn't Postgres (sqlite in tests), this module no-ops gracefully —
the worker falls back to pure polling.
"""
from __future__ import annotations

import logging
import select
import time
from contextlib import contextmanager
from typing import Iterator, Optional, Set

from sqlalchemy.engine import Engine

logger = logging.getLogger(__name__)

CHANNEL_AGENT_TASK_READY = "agent_task_ready"


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


@contextmanager
def listen_connection(
    engine: Engine,
    channel: str = CHANNEL_AGENT_TASK_READY,
) -> Iterator[Optional[object]]:
    """Yield a raw psycopg2 connection that's LISTENing on *channel*.

    Yields None on non-Postgres engines so callers can fall through to polling.
    The connection is set to AUTOCOMMIT so LISTEN takes effect immediately
    instead of waiting for the next transaction commit.
    """
    if not is_postgres(engine):
        yield None
        return

    raw = engine.raw_connection()
    underlying = None
    try:
        # SQLAlchemy wraps the DBAPI connection; the real psycopg2 conn is .connection
        underlying = getattr(raw, "connection", raw)
        try:
            import psycopg2.extensions
            underlying.set_isolation_level(
                psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT
            )
        except Exception:  # noqa: BLE001
            logger.debug("[notify_listener] could not set autocommit", exc_info=True)

        cur = underlying.cursor()
        cur.execute(f"LISTEN {channel};")
        cur.close()
        logger.info("[notify_listener] LISTENing on '%s'", channel)
        yield underlying
    finally:
        try:
            raw.close()
        except Exception:  # noqa: BLE001
            pass


def wait_for_notify(
    connection: Optional[object],
    timeout_seconds: float,
) -> Set[str]:
    """Block up to *timeout_seconds* waiting for notifications on *connection*.

    Returns the set of unique payloads received in this wait window. An empty
    set means the timeout fired without a notification — caller should run a
    full poll cycle.

    If *connection* is None (non-Postgres engine), sleeps for the timeout and
    returns an empty set so polling-fallback semantics still hold.
    """
    if connection is None:
        time.sleep(timeout_seconds)
        return set()

    payloads: Set[str] = set()
    try:
        ready, _, _ = select.select([connection], [], [], timeout_seconds)
        if not ready:
            return payloads
        connection.poll()
        while connection.notifies:
            n = connection.notifies.pop(0)
            if n.payload:
                payloads.add(n.payload)
    except (OSError, ValueError) as exc:
        # Connection dropped — caller's outer loop will re-establish on next pass.
        logger.warning("[notify_listener] wait_for_notify error: %s", exc)
    return payloads


def notify(session, company_id: int, channel: str = CHANNEL_AGENT_TASK_READY) -> None:
    """Queue a `pg_notify` inside the current transaction.

    No-op on non-Postgres dialects so sqlite tests don't fail. The notification
    is delivered to listeners on the surrounding transaction's COMMIT — if the
    transaction rolls back the notification is dropped, so this is automatically
    transactional with the row insert.
    """
    bind = session.get_bind()
    if not is_postgres(bind):
        return
    try:
        from sqlalchemy import text
        session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": channel, "payload": str(int(company_id))},
        )
    except Exception:  # noqa: BLE001
        # NOTIFY is best-effort — polling tick is the safety net.
        logger.debug("[notify_listener] pg_notify failed (non-fatal)", exc_info=True)
