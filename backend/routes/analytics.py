from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select, func, text
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from database import get_session
from models.models import LatencyLog, User
from auth import get_current_user
from services.analytics_service import (
    create_alert,
    evaluate_alerts,
    get_campaign_drilldown,
    get_engagement_summary,
    get_quote_timeline_csv,
    list_alerts,
)
from pydantic import BaseModel
from decimal import Decimal


class AlertRequest(BaseModel):
    metric: str
    threshold: Decimal
    direction: str = "gte"
    channel: str = "email"


router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/latency")
async def get_latency_analytics(
    days: int = 7,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scope: str = "mine",  # mine | all (company_admin only)
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user)
):
    """
    Real-time latency analytics from LatencyLog table.
    Returns engine summaries, per-call breakdowns, model rankings, and daily trends.
    Supports fixed 'days' or dynamic 'start_date'/'end_date' (YYYY-MM-DD).
    """
    if start_date and end_date:
        try:
            cutoff_start = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            cutoff_end = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            cutoff = cutoff_start # Primary filter
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD.")
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        cutoff_start = cutoff
        cutoff_end = datetime.now(timezone.utc) + timedelta(days=1)

    # Per-engine aggregates (turn-level rows)
    engine_query = (
        select(
            LatencyLog.engine,
            func.count(LatencyLog.id).label("rows"),
            func.avg(LatencyLog.stt_ms).label("stt_avg"),
            func.avg(LatencyLog.llm_ms).label("llm_avg"),
            func.avg(LatencyLog.tts_ms).label("tts_avg"),
            func.avg(LatencyLog.total_ms).label("total_avg"),
            func.min(LatencyLog.total_ms).label("total_min"),
            func.max(LatencyLog.total_ms).label("total_max"),
        )
        .where(LatencyLog.created_at >= cutoff_start)
        .where(LatencyLog.created_at < cutoff_end)
        .where(LatencyLog.engine.is_not(None))
        .where(LatencyLog.company_id == current_user.company_id)
    )

    if scope != "all":
        engine_query = engine_query.where(LatencyLog.user_id == current_user.id)

    engine_query = engine_query.group_by(LatencyLog.engine).order_by(func.avg(LatencyLog.total_ms))

    engine_rows = session.exec(engine_query).all()

    engines = [
        {
            "engine": r.engine,
            "rows": r.rows,
            "stt_avg": round(r.stt_avg or 0, 1),
            "llm_avg": round(r.llm_avg or 0, 1),
            "tts_avg": round(r.tts_avg or 0, 1),
            "total_avg": round(r.total_avg or 0, 1),
            "total_min": round(r.total_min or 0, 1),
            "total_max": round(r.total_max or 0, 1),
        }
        for r in engine_rows
    ]

    # Per-interaction (call-level) aggregates
    interaction_query = (
        select(
            LatencyLog.interaction_id,
            LatencyLog.engine,
            LatencyLog.stt_model,
            LatencyLog.llm_model,
            LatencyLog.tts_model,
            func.count(LatencyLog.id).label("turns"),
            func.avg(LatencyLog.stt_ms).label("stt_avg"),
            func.avg(LatencyLog.llm_ms).label("llm_avg"),
            func.avg(LatencyLog.tts_ms).label("tts_avg"),
            func.avg(LatencyLog.total_ms).label("total_avg"),
            func.min(LatencyLog.total_ms).label("total_min"),
            func.max(LatencyLog.total_ms).label("total_max"),
        )
        .where(LatencyLog.created_at >= cutoff_start)
        .where(LatencyLog.created_at < cutoff_end)
        .where(LatencyLog.interaction_id.is_not(None))
        .where(LatencyLog.company_id == current_user.company_id)
    )

    if scope != "all":
        interaction_query = interaction_query.where(LatencyLog.user_id == current_user.id)

    interaction_query = (
        interaction_query.group_by(
            LatencyLog.interaction_id,
            LatencyLog.engine,
            LatencyLog.stt_model,
            LatencyLog.llm_model,
            LatencyLog.tts_model,
        )
        .order_by(LatencyLog.interaction_id.desc())
        .limit(50)
    )

    interaction_rows = session.exec(interaction_query).all()

    interactions = [
        {
            "id": r.interaction_id,
            "engine": r.engine,
            "stt_model": r.stt_model or "—",
            "llm_model": r.llm_model or "—",
            "tts_model": r.tts_model or "—",
            "turns": r.turns,
            "stt_avg": round(r.stt_avg or 0, 1),
            "llm_avg": round(r.llm_avg or 0, 1),
            "tts_avg": round(r.tts_avg or 0, 1),
            "total_avg": round(r.total_avg or 0, 1),
            "total_min": round(r.total_min or 0, 1),
            "total_max": round(r.total_max or 0, 1),
        }
        for r in interaction_rows
    ]

    # Model-level breakdowns (STT / LLM / TTS)
    def fetch_model_stats(model_col, ms_col, provider_col):
        rows = session.exec(
            (
                select(
                    model_col,
                    provider_col,
                    func.count(LatencyLog.id).label("rows"),
                    func.avg(ms_col).label("avg"),
                    func.min(ms_col).label("min"),
                    func.max(ms_col).label("max"),
                )
                .where(LatencyLog.created_at >= cutoff_start)
                .where(LatencyLog.created_at < cutoff_end)
                .where(LatencyLog.company_id == current_user.company_id)
                .where(ms_col > 0)
                .where(model_col.is_not(None))
                .group_by(model_col, provider_col)
                .order_by(func.avg(ms_col))
            )
        ).all()
        return [
            {
                "model": r[0],
                "provider": r[1] or "—",
                "rows": r[2],
                "avg": round(r[3] or 0, 1),
                "min": round(r[4] or 0, 1),
                "max": round(r[5] or 0, 1),
            }
            for r in rows
        ]

    stt_models = fetch_model_stats(LatencyLog.stt_model, LatencyLog.stt_ms, LatencyLog.stt_provider)
    llm_models = fetch_model_stats(LatencyLog.llm_model, LatencyLog.llm_ms, LatencyLog.llm_provider)
    tts_models = fetch_model_stats(LatencyLog.tts_model, LatencyLog.tts_ms, LatencyLog.tts_provider)

    # Daily trend per engine
    trend_raw = session.execute(
        text("""
            SELECT
                DATE(created_at) AS day,
                engine,
                ROUND(AVG(total_ms)::numeric, 1) AS avg_ms,
                COUNT(*) AS turns
            FROM latencylog
            WHERE created_at >= :cutoff_start AND created_at < :cutoff_end
              AND engine IS NOT NULL
            GROUP BY DATE(created_at), engine
            ORDER BY day ASC, avg_ms ASC
        """),
        {"cutoff_start": cutoff_start, "cutoff_end": cutoff_end},
    ).all()

    trend = [
        {"day": str(r[0]), "engine": r[1], "avg_ms": float(r[2] or 0), "turns": r[3]}
        for r in trend_raw
    ]

    total_turns = sum(e["rows"] for e in engines)
    total_calls = len(set(r.interaction_id for r in interaction_rows))

    return {
        "engines": engines,
        "interactions": interactions,
        "stt_models": stt_models,
        "llm_models": llm_models,
        "tts_models": tts_models,
        "trend": trend,
        "meta": {
            "days": days,
            "total_turns": total_turns,
            "total_calls": total_calls,
        },
    }


@router.get("/my-latency")
async def get_my_latency_logs(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
    limit: int = 100,
    offset: int = 0,
):
    """Return latency logs belonging to current authenticated user."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=400, detail="limit must be 1..1000")

    rows = session.exec(
        select(LatencyLog)
        .where(LatencyLog.user_id == current_user.id)
        .order_by(LatencyLog.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()

    return {
        "user_id": current_user.id,
        "total": len(rows),
        "logs": [
            {
                "id": r.id,
                "interaction_id": r.interaction_id,
                "engine": r.engine,
                "stt_ms": r.stt_ms,
                "llm_ms": r.llm_ms,
                "tts_ms": r.tts_ms,
                "total_ms": r.total_ms,
                "stt_provider": r.stt_provider,
                "llm_provider": r.llm_provider,
                "tts_provider": r.tts_provider,
                "created_at": r.created_at,
            }
            for r in rows
        ],
    }


@router.get("/engagement-summary")
async def engagement_summary(
    days: int = 7,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if days < 1:
        raise HTTPException(status_code=400, detail="days must be >= 1")
    return get_engagement_summary(session, current_user.company_id, lookback_days=days)


@router.get("/campaign-drilldown")
async def campaign_drilldown(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return get_campaign_drilldown(session, current_user.company_id, campaign_id)


@router.get("/quote/export")
async def quote_export(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    csv = get_quote_timeline_csv(session, current_user.company_id)
    headers = {
        "Content-Disposition": "attachment; filename=quote_timeline.csv",
    }
    return Response(content=csv, media_type="text/csv", headers=headers)


@router.get("/alerts")
async def analytics_alerts(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list_alerts(session, current_user.company_id)


@router.post("/alerts")
async def analytics_alert_create(
    payload: AlertRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return create_alert(
        session=session,
        company_id=current_user.company_id,
        metric=payload.metric,
        threshold=payload.threshold,
        direction=payload.direction,
        channel=payload.channel,
    )


@router.post("/alerts/evaluate")
async def analytics_alert_evaluate(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return evaluate_alerts(session, current_user.company_id)
