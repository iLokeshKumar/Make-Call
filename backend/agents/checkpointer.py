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
_async_checkpointer = None


def get_checkpointer():
    """
    Return a singleton synchronous checkpointer instance.
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


async def get_async_checkpointer():
    """
    Return a singleton asynchronous checkpointer instance.
    Essential for graphs called via .ainvoke() to avoid NotImplementedError.
    """
    global _async_checkpointer
    if _async_checkpointer is not None:
        return _async_checkpointer

    mode = os.getenv("LANGGRAPH_CHECKPOINTER", "memory").lower()

    if mode == "postgres":
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url or db_url.startswith("sqlite"):
            # If DB URL is wrong, we can't do async postgres, fall back to sync memory via a temporary async wrapper or just return MemorySaver
            from langgraph.checkpoint.memory import MemorySaver
            _async_checkpointer = MemorySaver()
            return _async_checkpointer
        
        try:
            from psycopg_pool import AsyncConnectionPool
            from psycopg.rows import dict_row
            from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

            # Build a long-lived async pool and open it explicitly (avoid deprecated constructor behavior)
            pool = AsyncConnectionPool(
                conninfo=db_url,
                max_size=10,
                open=False,
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
            )
            await pool.open()
            saver = AsyncPostgresSaver(pool)
            await saver.setup()
            _async_checkpointer = saver
            logger.info("[Checkpointer] Using AsyncPostgresSaver (persistent memory)")
            return _async_checkpointer
        except Exception as exc:
            logger.warning(
                "[Checkpointer] AsyncPostgresSaver unavailable (%s), falling back to MemorySaver",
                exc,
            )

    from langgraph.checkpoint.memory import MemorySaver
    _async_checkpointer = MemorySaver()
    logger.info("[Checkpointer] Using MemorySaver (in-memory async)")
    return _async_checkpointer

async def close_checkpointer():
    global _async_checkpointer
    if _async_checkpointer and hasattr(_async_checkpointer, 'pool'):
        await _async_checkpointer.pool.close()