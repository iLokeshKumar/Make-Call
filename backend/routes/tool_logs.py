"""GET /crm/tool-logs — admin view of tool call history."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ToolCallLog, User

router = APIRouter(prefix="/crm/tool-logs", tags=["Tool Logs"])


@router.get("")
def list_tool_logs(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    tool_name: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    current_user: User = Depends(PermissionChecker("analytics.read_company")),
    session: Session = Depends(get_session),
):
    stmt = (
        select(ToolCallLog)
        .where(ToolCallLog.company_id == current_user.company_id)
        .order_by(ToolCallLog.created_at.desc())
    )
    if tool_name:
        stmt = stmt.where(ToolCallLog.tool_name == tool_name)
    if status:
        stmt = stmt.where(ToolCallLog.status == status)

    rows = session.exec(stmt.offset(offset).limit(limit)).all()
    total = session.exec(
        select(ToolCallLog).where(ToolCallLog.company_id == current_user.company_id)
    )

    return {
        "logs": [
            {
                "id": r.id,
                "tool_name": r.tool_name,
                "status": r.status,
                "duration_ms": r.duration_ms,
                "error_message": r.error_message,
                "user_id": r.user_id,
                "interaction_id": r.interaction_id,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/summary")
def tool_log_summary(
    lookback_days: int = Query(default=7, le=90),
    current_user: User = Depends(PermissionChecker("analytics.read_company")),
    session: Session = Depends(get_session),
):
    from datetime import timedelta
    from models.models import utc_now
    from sqlalchemy import func

    since = utc_now() - timedelta(days=lookback_days)

    rows = session.exec(
        select(
            ToolCallLog.tool_name,
            ToolCallLog.status,
            func.count(ToolCallLog.id).label("count"),
            func.avg(ToolCallLog.duration_ms).label("avg_ms"),
        )
        .where(
            ToolCallLog.company_id == current_user.company_id,
            ToolCallLog.created_at >= since,
        )
        .group_by(ToolCallLog.tool_name, ToolCallLog.status)
        .order_by(func.count(ToolCallLog.id).desc())
    ).all()

    # Aggregate per tool
    by_tool: dict = {}
    for tool_name, status, count, avg_ms in rows:
        if tool_name not in by_tool:
            by_tool[tool_name] = {"tool_name": tool_name, "total": 0, "success": 0, "error": 0, "timeout": 0, "avg_ms": 0}
        by_tool[tool_name]["total"] += count
        by_tool[tool_name][status] = count
        by_tool[tool_name]["avg_ms"] = round(float(avg_ms or 0))

    return {
        "summary": list(by_tool.values()),
        "lookback_days": lookback_days,
    }
