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
_async_checkpointers = {}


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
    Return a singleton asynchronous checkpointer instance per event loop.
    Essential for graphs called via .ainvoke() to avoid NotImplementedError
    and different event loop lock errors.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop in _async_checkpointers:
        return _async_checkpointers[loop]

    mode = os.getenv("LANGGRAPH_CHECKPOINTER", "memory").lower()
    saver = None

    if mode == "postgres":
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url or db_url.startswith("sqlite"):
            from langgraph.checkpoint.memory import MemorySaver
            saver = MemorySaver()
        else:
            try:
                from psycopg_pool import AsyncConnectionPool
                from psycopg.rows import dict_row
                from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

                pool = AsyncConnectionPool(
                    conninfo=db_url,
                    max_size=10,
                    open=False,
                    kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                )
                await pool.open()
                saver = AsyncPostgresSaver(pool)
                await saver.setup()
                logger.info("[Checkpointer] Using AsyncPostgresSaver (persistent memory)")
            except Exception as exc:
                logger.warning(
                    "[Checkpointer] AsyncPostgresSaver unavailable (%s), falling back to MemorySaver",
                    exc,
                )

    if not saver:
        from langgraph.checkpoint.memory import MemorySaver
        saver = MemorySaver()
        logger.info("[Checkpointer] Using MemorySaver (in-memory async)")

    if loop:
        _async_checkpointers[loop] = saver
    return saver

async def close_checkpointer():
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop in _async_checkpointers:
        saver = _async_checkpointers[loop]
        if hasattr(saver, 'pool'):
            await saver.pool.close()