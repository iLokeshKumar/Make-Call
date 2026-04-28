from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import Response
from sqlmodel import Session, select, func, text
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from database import get_session
from models.models import AnalyticsAlert, LatencyLog, User
from auth import get_current_user
from services.core.auth_service import user_has_any_permission
from services.analytics.analytics_service import (
    create_alert,
    evaluate_alerts,
    get_call_conversion_summary,
    get_call_performance_metrics,
    get_campaign_drilldown,
    get_campaign_email_report,
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


def _resolve_scope_user_id(session: Session, current_user: User) -> int | None:
    """Return current_user.id if they only have analytics.read_own, else None (company-wide)."""
    can_read_company = user_has_any_permission(session, current_user.id, {"analytics.read_company"})
    if can_read_company:
        return None
    return current_user.id


@router.get("/latency")
async def get_latency_analytics(
    days: int = 7,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    scope: str = "all",  # all | mine
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

    # Per-engine aggregates (turn-level rows). p95 via Postgres percentile_cont; actionable for provider-pick decisions in /settings (see docs/VOICE_TUNING.md).
    scope_filter = "AND user_id = :user_id" if scope != "all" else ""
    engine_rows = session.execute(
        text(f"""
            SELECT
                engine,
                COUNT(id) AS rows,
                AVG(stt_ms) AS stt_avg,
                AVG(llm_ms) AS llm_avg,
                AVG(tts_ms) AS tts_avg,
                AVG(total_ms) AS total_avg,
                MIN(total_ms) AS total_min,
                MAX(total_ms) AS total_max,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY total_ms) AS total_p95,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY llm_ms)   AS llm_p95
            FROM latencylog
            WHERE created_at >= :cutoff_start
              AND created_at <  :cutoff_end
              AND engine IS NOT NULL
              AND company_id = :company_id
              {scope_filter}
            GROUP BY engine
            ORDER BY AVG(total_ms)
        """),
        {
            "cutoff_start": cutoff_start,
            "cutoff_end": cutoff_end,
            "company_id": current_user.company_id,
            **({"user_id": current_user.id} if scope != "all" else {}),
        },
    ).all()

    engines = [
        {
            "engine": r[0],
            "rows": r[1],
            "stt_avg": round(float(r[2] or 0), 1),
            "llm_avg": round(float(r[3] or 0), 1),
            "tts_avg": round(float(r[4] or 0), 1),
            "total_avg": round(float(r[5] or 0), 1),
            "total_min": round(float(r[6] or 0), 1),
            "total_max": round(float(r[7] or 0), 1),
            "total_p95": round(float(r[8] or 0), 1),
            "llm_p95":   round(float(r[9] or 0), 1),
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

    # Daily trend per engine — company_id filter is mandatory (tenant isolation)
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
              AND company_id = :company_id
            GROUP BY DATE(created_at), engine
            ORDER BY day ASC, avg_ms ASC
        """),
        {"cutoff_start": cutoff_start, "cutoff_end": cutoff_end, "company_id": current_user.company_id},
    ).all()

    trend = [
        {"day": str(r[0]), "engine": r[1], "avg_ms": float(r[2] or 0), "turns": r[3]}
        for r in trend_raw
    ]

    total_turns = sum(e["rows"] for e in engines)
    total_calls = len(set(r.interaction_id for r in interaction_rows))

    # CSAT-by-LLM-provider — joins customer-source Feedback rows for each interaction back to the engine that handled it.  Lets the user see not just "which provider is fastest" but "which provider customers actually rated highest".  Tenant-scoped by company_id.
    csat_rows = session.execute(
        text("""
            SELECT
                ll.llm_provider                AS provider,
                ROUND(AVG(fb.rating)::numeric, 2) AS csat_avg,
                COUNT(DISTINCT fb.id)          AS csat_count
            FROM feedback fb
            JOIN latencylog ll
              ON ll.interaction_id = fb.interaction_id
            WHERE fb.company_id = :company_id
              AND fb.source = 'customer'
              AND fb.feedback_type = 'csat'
              AND fb.rating IS NOT NULL
              AND fb.created_at >= :cutoff_start
              AND fb.created_at <  :cutoff_end
              AND ll.llm_provider IS NOT NULL
            GROUP BY ll.llm_provider
            ORDER BY csat_avg DESC NULLS LAST
        """),
        {"cutoff_start": cutoff_start, "cutoff_end": cutoff_end, "company_id": current_user.company_id},
    ).all()
    csat_by_provider = [
        {"provider": r[0], "csat_avg": float(r[1] or 0), "csat_count": int(r[2] or 0)}
        for r in csat_rows
    ]

    return {
        "engines": engines,
        "interactions": interactions,
        "stt_models": stt_models,
        "llm_models": llm_models,
        "tts_models": tts_models,
        "trend": trend,
        "csat_by_provider": csat_by_provider,
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
    days: int = 30,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    since: Optional[datetime] = None
    until: Optional[datetime] = None
    if date_from:
        try:
            since = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from format (use YYYY-MM-DD)")
    if date_to:
        try:
            until = datetime.fromisoformat(date_to).replace(hour=23, minute=59, second=59, tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to format (use YYYY-MM-DD)")
    if since is None:
        if days < 1:
            raise HTTPException(status_code=400, detail="days must be >= 1")
        since = datetime.now(timezone.utc) - timedelta(days=days)
    scope_user_id = _resolve_scope_user_id(session, current_user)
    return get_engagement_summary(session, current_user.company_id, since=since, until=until, scope_user_id=scope_user_id)


@router.get("/call-conversion")
async def call_conversion(
    days: int = 30,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Call-to-outcome conversion rates for the last N days.
    Sales reps see only their own metrics; admins/owners see company-wide.
    """
    scope_user_id = _resolve_scope_user_id(session, current_user)
    return get_call_conversion_summary(session, current_user.company_id, days=days, scope_user_id=scope_user_id)


@router.get("/call-performance")
async def call_performance(
    days: int = 30,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Call performance metrics for the Performance dashboard tab.
    Sales reps see only their own metrics; admins/owners see company-wide.
    """
    scope_user_id = _resolve_scope_user_id(session, current_user)
    return get_call_performance_metrics(session, current_user.company_id, days=days, scope_user_id=scope_user_id)


@router.get("/campaign-drilldown")
async def campaign_drilldown(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return get_campaign_drilldown(session, current_user.company_id, campaign_id)


@router.get("/campaign/{campaign_id}/email-report")
async def campaign_email_report(
    campaign_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    result = get_campaign_email_report(session, current_user.company_id, campaign_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


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


@router.patch("/alerts/{alert_id}/enable")
async def analytics_alert_enable(
    alert_id: int = Path(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    alert = session.get(AnalyticsAlert, alert_id)
    if not alert or alert.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.enabled = True
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


@router.patch("/alerts/{alert_id}/disable")
async def analytics_alert_disable(
    alert_id: int = Path(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    alert = session.get(AnalyticsAlert, alert_id)
    if not alert or alert.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    alert.enabled = False
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


@router.delete("/alerts/{alert_id}")
async def analytics_alert_delete(
    alert_id: int = Path(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    alert = session.get(AnalyticsAlert, alert_id)
    if not alert or alert.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    session.delete(alert)
    session.commit()
    return {"deleted": True, "alert_id": alert_id}


@router.get("/latency/trace/{trace_id}")
async def get_latency_trace(
    trace_id: str = Path(..., description="Call trace_id — UUID hex from LatencyLog"),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return the full per-turn STT→LLM→TTS waterfall for a single call.
    Turns are ordered by turn_index (ascending).
    """
    rows = session.exec(
        select(LatencyLog)
        .where(LatencyLog.trace_id == trace_id)
        .where(LatencyLog.company_id == current_user.company_id)
        .order_by(LatencyLog.turn_index)
    ).all()

    if not rows:
        raise HTTPException(status_code=404, detail="Trace not found")

    return {
        "trace_id": trace_id,
        "turns": [
            {
                "turn_index": r.turn_index,
                "span_id": r.span_id,
                "span_status": r.span_status or "ok",
                "engine": r.engine,
                "stt_ms": float(r.stt_ms),
                "llm_ms": float(r.llm_ms),
                "tts_ms": float(r.tts_ms),
                "total_ms": float(r.total_ms),
                "stt_provider": r.stt_provider,
                "llm_provider": r.llm_provider,
                "tts_provider": r.tts_provider,
                "stt_model": r.stt_model,
                "llm_model": r.llm_model,
                "tts_model": r.tts_model,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "summary": {
            "total_turns": len(rows),
            "stt_avg_ms": round(sum(float(r.stt_ms) for r in rows) / len(rows), 1),
            "llm_avg_ms": round(sum(float(r.llm_ms) for r in rows) / len(rows), 1),
            "tts_avg_ms": round(sum(float(r.tts_ms) for r in rows) / len(rows), 1),
            "total_avg_ms": round(sum(float(r.total_ms) for r in rows) / len(rows), 1),
            "errors": sum(1 for r in rows if r.span_status == "error"),
        },
    }


@router.get("/latency/by-interaction/{interaction_id}")
async def get_latency_by_interaction(
    interaction_id: int = Path(...),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """
    Return all LatencyLog turns for an interaction, with trace context.
    Useful for debugging a specific call from the lead detail page.
    """
    rows = session.exec(
        select(LatencyLog)
        .where(LatencyLog.interaction_id == interaction_id)
        .where(LatencyLog.company_id == current_user.company_id)
        .order_by(LatencyLog.turn_index.nulls_last(), LatencyLog.id)
    ).all()

    if not rows:
        raise HTTPException(status_code=404, detail="No latency data for this interaction")

    trace_id = next((r.trace_id for r in rows if r.trace_id), None)

    return {
        "interaction_id": interaction_id,
        "trace_id": trace_id,
        "turns": [
            {
                "turn_index": r.turn_index,
                "span_id": r.span_id,
                "span_status": r.span_status or "ok",
                "stt_ms": float(r.stt_ms),
                "llm_ms": float(r.llm_ms),
                "tts_ms": float(r.tts_ms),
                "total_ms": float(r.total_ms),
            }
            for r in rows
        ],
    }
