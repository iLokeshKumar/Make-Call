from fastapi import APIRouter, Depends
from sqlmodel import Session, select, func, text
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from database import get_session
from models.models import LatencyLog, User
from auth import get_current_active_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])

@router.get("/latency")
async def get_latency_analytics(
    days: int = 7,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
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

    # ── 1. Per-engine aggregates (turn-level rows)
    engine_rows = session.exec(
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
        .group_by(LatencyLog.engine)
        .order_by(func.avg(LatencyLog.total_ms))
    ).all()

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

    # ── 2. Per-interaction (call-level) aggregates
    interaction_rows = session.exec(
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
        .group_by(
            LatencyLog.interaction_id,
            LatencyLog.engine,
            LatencyLog.stt_model,
            LatencyLog.llm_model,
            LatencyLog.tts_model,
        )
        .order_by(LatencyLog.interaction_id.desc())
        .limit(50)
    ).all()

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

    # ── 3. Model-level breakdowns (STT / LLM / TTS)
    def fetch_model_stats(model_col, ms_col, provider_col):
        rows = session.exec(
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
            .where(ms_col > 0)
            .where(model_col.is_not(None))
            .group_by(model_col, provider_col)
            .order_by(func.avg(ms_col))
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

    # ── 4. Daily trend per engine
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

    return {
        "engines": engines,
        "interactions": interactions,
        "stt_models": stt_models,
        "llm_models": llm_models,
        "tts_models": tts_models,
        "trend": trend,
        "meta": {
            "days": days,
            "total_turns": sum(e["rows"] for e in engines),
            "total_calls": len(interactions),
        },
    }