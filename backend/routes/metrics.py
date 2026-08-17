"""Metrics ingest — frontend beacons + observability dashboards.

Cookie-auth only (no API key).  Payloads are tiny and the data feeds
SLO #2 (login → dashboard p95).
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import UiLatencyLog, User

router = APIRouter(prefix="/metrics", tags=["Metrics"])


class UiLatencyBeacon(BaseModel):
    route: str = Field(max_length=120)
    event: Literal["ttfb", "fmp", "tti", "load"] = "fmp"
    duration_ms: int = Field(ge=0, le=600_000)


@router.post("/ui-latency")
async def ingest_ui_latency(
    payload: UiLatencyBeacon,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict:
    """Frontend reports first-meaningful-paint / TTFB / TTI of a route.

    Stored as a UiLatencyLog row.  Aggregated by /admin/slo-status into
    the login → dashboard p95 SLO.
    """
    row = UiLatencyLog(
        company_id=current_user.company_id,
        user_id=current_user.id,
        route=payload.route[:120],
        event=payload.event,
        duration_ms=int(payload.duration_ms),
    )
    session.add(row)
    session.commit()
    return {"status": "recorded"}
