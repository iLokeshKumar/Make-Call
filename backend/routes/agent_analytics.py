"""Agent Performance analytics — thin HTTP layer over analytics_service.

Four endpoints, one per dashboard chart:
  GET /agent-analytics/dispatches-by-channel?days=30
  GET /agent-analytics/channel-funnel?days=30
  GET /agent-analytics/cost-by-stage?days=7
  GET /agent-analytics/latency-percentiles?days=7

All read-only; require agent.manage OR analytics.read_company permission.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import User
from services.agent.analytics_service import (
    channel_funnel,
    cost_by_stage,
    dispatches_by_channel_daily,
    latency_percentiles_by_task_type,
)

router = APIRouter(prefix="/agent-analytics", tags=["Agent Analytics"])


@router.get("/dispatches-by-channel")
async def get_dispatches_by_channel(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    return dispatches_by_channel_daily(session, current_user.company_id, days=days)


@router.get("/channel-funnel")
async def get_channel_funnel(
    days: int = Query(default=30, ge=1, le=365),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    return channel_funnel(session, current_user.company_id, days=days)


@router.get("/cost-by-stage")
async def get_cost_by_stage(
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    return cost_by_stage(session, current_user.company_id, days=days)


@router.get("/latency-percentiles")
async def get_latency_percentiles(
    days: int = Query(default=7, ge=1, le=90),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    return latency_percentiles_by_task_type(session, current_user.company_id, days=days)
