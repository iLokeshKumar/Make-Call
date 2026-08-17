"""
Async fire-and-forget tracer for tool calls.

Usage:
    asyncio.create_task(trace_tool_call(...))   # non-blocking
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


async def trace_tool_call(
    tool_name: str,
    company_id: int,
    status: str,          # "success" | "error" | "timeout"
    duration_ms: int,
    user_id: Optional[int] = None,
    interaction_id: Optional[int] = None,
    error_message: Optional[str] = None,
) -> None:
    """Write one ToolCallLog row. Designed to be fire-and-forgotten via create_task()."""
    try:
        from database import engine, rls_company_id
        from models.models import ToolCallLog
        from sqlmodel import Session

        def _write() -> None:
            token = rls_company_id.set(company_id)
            try:
                with Session(engine) as session:
                    session.add(ToolCallLog(
                        company_id=company_id,
                        user_id=user_id,
                        interaction_id=interaction_id,
                        tool_name=tool_name,
                        status=status,
                        duration_ms=duration_ms,
                        error_message=(error_message or "")[:500] if error_message else None,
                    ))
                    session.commit()
            finally:
                rls_company_id.reset(token)

        await asyncio.to_thread(_write)
    except Exception as exc:
        logger.warning("[tool_tracer] Failed to log tool call %s: %s", tool_name, exc)
