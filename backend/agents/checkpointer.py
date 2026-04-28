"""
LangGraph checkpointer — provides stateful agent memory across invocations.

Default: MemorySaver (in-process, lost on restart).
Production upgrade: set LANGGRAPH_CHECKPOINTER=postgres and ensure DATABASE_URL
  is set + langgraph-checkpoint-postgres is installed with libpq available.

Usage:
    from agents.checkpointer import get_checkpointer
    app = workflow.compile(checkpointer=get_checkpointer())
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_checkpointer = None


def get_checkpointer():
    """
    Return a singleton checkpointer instance.

    - LANGGRAPH_CHECKPOINTER=postgres  → PostgresSaver (persistent across restarts)
    - anything else (default)          → MemorySaver  (in-memory, dev-friendly)
    """
    global _checkpointer
    if _checkpointer is not None:
        return _checkpointer

    mode = os.getenv("LANGGRAPH_CHECKPOINTER", "memory").lower()

    if mode == "postgres":
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url or db_url.startswith("sqlite"):
            logger.warning(
                "[Checkpointer] DATABASE_URL is not Postgres (got %s), falling back to MemorySaver",
                "missing" if not db_url else "sqlite",
            )
        else:
            try:
                # Modern langgraph-checkpoint-postgres returns a context
                # manager from from_conn_string — but we want a long-lived
                # singleton.  Build a ConnectionPool + PostgresSaver
                # directly so the saver lives across cycles.
                from psycopg_pool import ConnectionPool
                from psycopg.rows import dict_row
                from langgraph.checkpoint.postgres import PostgresSaver

                pool = ConnectionPool(
                    conninfo=db_url,
                    max_size=10,
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                )
                saver = PostgresSaver(pool)
                saver.setup()  # creates checkpoint_* tables if missing (idempotent)
                _checkpointer = saver
                logger.info("[Checkpointer] Using PostgresSaver (persistent memory)")
                return _checkpointer
            except Exception as exc:
                logger.warning(
                    "[Checkpointer] PostgresSaver unavailable (%s), falling back to MemorySaver",
                    exc,
                )

    from langgraph.checkpoint.memory import MemorySaver
    _checkpointer = MemorySaver()
    logger.info("[Checkpointer] Using MemorySaver (in-memory)")
    return _checkpointer
