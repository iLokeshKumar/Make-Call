from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case
from sqlmodel import Session, select, func

from models.models import AnalyticsAlert, Appointment, EngagementEvent, CallTask, Campaign, CampaignRecipient, Interaction, Lead, Quote, utc_now


def _query_counts(session: Session, company_id: int, model, column):
    rows = session.exec(
        select(column, func.count(model.id))
        .where(model.company_id == company_id)
        .group_by(column)
    ).all()
    return {row[0]: row[1] for row in rows if row[0]}


def _build_funnel(counts: dict[str, int]) -> list[dict]:
    total = sum(counts.values())
    if total == 0:
        return []
    return [
        {
            "status": status,
            "count": count,
            "percent": round((count / total) * 100, 1),
        }
        for status, count in sorted(counts.items(), key=lambda item: item[1], reverse=True)
    ]


def get_engagement_summary(
    session: Session,
    company_id: int,
    lookback_days: int = 30,
    since: datetime | None = None,
    until: datetime | None = None,
    scope_user_id: int | None = None,
) -> dict:
    if since is None:
        since = utc_now() - timedelta(days=lookback_days)

    def _since_filter(col):
        filters = [col >= since]
        if until is not None:
            filters.append(col <= until)
        return filters

    # Base engagement event filters
    ee_base = [EngagementEvent.company_id == company_id]
    if scope_user_id:
        # EngagementEvent has no user_id — scope via lead ownership
        user_lead_ids = select(Lead.id).where(
            Lead.company_id == company_id,
            Lead.owner_user_id == scope_user_id,
            Lead.deleted_at.is_(None),
        )
        ee_base.append(EngagementEvent.lead_id.in_(user_lead_ids))

    event_rows = session.exec(
        select(EngagementEvent.event_type, func.count(EngagementEvent.id))
        .where(*ee_base)
        .where(*_since_filter(EngagementEvent.created_at))
        .group_by(EngagementEvent.event_type)
    ).all()
    event_counts = {row[0]: row[1] for row in event_rows if row[0]}

    channel_rows = session.exec(
        select(EngagementEvent.channel, func.count(EngagementEvent.id))
        .where(*ee_base)
        .where(*_since_filter(EngagementEvent.created_at))
        .group_by(EngagementEvent.channel)
    ).all()
    channel_counts = {row[0]: row[1] for row in channel_rows if row[0]}

    timeline_rows = session.exec(
        select(
            func.date(EngagementEvent.created_at).label("day"),
            EngagementEvent.event_type,
            func.count(EngagementEvent.id),
        )
        .where(*ee_base)
        .where(*_since_filter(EngagementEvent.created_at))
        .group_by(func.date(EngagementEvent.created_at), EngagementEvent.event_type)
        .order_by(func.date(EngagementEvent.created_at))
    ).all()
    timeline = [
        {"day": str(row[0]), "event_type": row[1], "count": row[2]}
        for row in timeline_rows
        if row[0] and row[1]
    ]

    quote_status_rows = session.exec(
        select(Quote.status, func.count(Quote.id))
        .where(Quote.company_id == company_id, Quote.deleted_at.is_(None))
        .group_by(Quote.status)
    ).all()
    quote_status_counts = {row[0]: row[1] for row in quote_status_rows if row[0]}
    call_status_counts = _query_counts(session, company_id, CallTask, CallTask.status)
    campaign_status_counts = _query_counts(
        session,
        company_id,
        CampaignRecipient,
        CampaignRecipient.status,
    )
    funnel = _build_funnel(campaign_status_counts)

    campaign_daily_rows = session.exec(
        select(
            func.date(CampaignRecipient.updated_at).label("day"),
            CampaignRecipient.status,
            func.count(CampaignRecipient.id),
        )
        .where(CampaignRecipient.company_id == company_id)
        .where(*_since_filter(CampaignRecipient.updated_at))
        .group_by(func.date(CampaignRecipient.updated_at), CampaignRecipient.status)
        .order_by(func.date(CampaignRecipient.updated_at))
    ).all()
    campaign_status_over_time = [
        {"day": str(row[0]), "status": row[1], "count": row[2]}
        for row in campaign_daily_rows
        if row[0] and row[1]
    ]

    conversion_rows = session.exec(
        select(
            Campaign.id,
            Campaign.name,
            func.sum(case((CampaignRecipient.status == "responded", 1), else_=0)).label("responded"),
            func.count(CampaignRecipient.id).label("recipients"),
        )
        .join(CampaignRecipient, CampaignRecipient.campaign_id == Campaign.id)
        .where(Campaign.company_id == company_id)
        .group_by(Campaign.id)
        .order_by(func.sum(case((CampaignRecipient.status == "responded", 1), else_=0)).desc())
    ).all()

    campaign_conversion_trends = [
        {
            "campaign_id": row[0],
            "name": row[1],
            "responded": row[2],
            "sent": row[3],
            "conversion_rate": round((row[2] / row[3]) * 100, 1) if row[3] else 0,
        }
        for row in conversion_rows
    ]

    quote_rows = session.exec(
        select(
            Quote.id,
            Quote.quote_number,
            Quote.status,
            Quote.created_at,
            Quote.sent_at,
            Quote.opened_at,
            Quote.accepted_at,
            Quote.rejected_at,
        )
        .where(Quote.company_id == company_id, Quote.deleted_at.is_(None))
        .order_by(Quote.created_at.desc())
        .limit(30)
    ).all()

    quote_timeline_export = [
        {
            "quote_id": row[0],
            "quote_number": row[1],
            "status": row[2],
            "dates": {
                "created_at": row[3].isoformat() if row[3] else None,
                "sent_at": row[4].isoformat() if row[4] else None,
                "opened_at": row[5].isoformat() if row[5] else None,
                "accepted_at": row[6].isoformat() if row[6] else None,
                "rejected_at": row[7].isoformat() if row[7] else None,
            },
        }
        for row in quote_rows
    ]

    return {
        "event_counts": event_counts,
        "channel_counts": channel_counts,
        "event_timeline": timeline,
        "quote_status_counts": quote_status_counts,
        "call_task_status_counts": call_status_counts,
        "campaign_status_counts": campaign_status_counts,
        "campaign_funnel": funnel,
        "campaign_conversion_trends": campaign_conversion_trends,
        "quote_timeline_export": quote_timeline_export,
        "campaign_status_over_time": campaign_status_over_time,
        "meta": {
            "lookback_days": lookback_days,
            "generated_at": utc_now(),
        },
    }


def get_quote_timeline_rows(session: Session, company_id: int, limit: int = 30) -> list[dict]:
    quotes = session.exec(
        select(
            Quote.id,
            Quote.quote_number,
            Quote.status,
            Quote.created_at,
            Quote.sent_at,
            Quote.opened_at,
            Quote.accepted_at,
            Quote.rejected_at,
        )
        .where(Quote.company_id == company_id, Quote.deleted_at.is_(None))
        .order_by(Quote.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "quote_id": row[0],
            "quote_number": row[1],
            "status": row[2],
            "dates": {
                "created_at": row[3].isoformat() if row[3] else None,
                "sent_at": row[4].isoformat() if row[4] else None,
                "opened_at": row[5].isoformat() if row[5] else None,
                "accepted_at": row[6].isoformat() if row[6] else None,
                "rejected_at": row[7].isoformat() if row[7] else None,
            },
        }
        for row in quotes
    ]


def get_quote_timeline_csv(session: Session, company_id: int, limit: int = 30) -> str:
    rows = get_quote_timeline_rows(session, company_id, limit)
    headers = "quote_id,quote_number,status,created_at,sent_at,opened_at,accepted_at,rejected_at"
    lines = [headers]
    for row in rows:
        dates = row["dates"]
        lines.append(
            ",".join(
                [
                    str(row["quote_id"]),
                    row["quote_number"],
                    row["status"],
                    dates["created_at"] or "",
                    dates["sent_at"] or "",
                    dates["opened_at"] or "",
                    dates["accepted_at"] or "",
                    dates["rejected_at"] or "",
                ]
            )
        )
    return "\n".join(lines)


def get_campaign_email_report(session: Session, company_id: int, campaign_id: int) -> dict:
    """
    Return email open/click/unsubscribe rates for a specific campaign.

    Counts:
    - emails_sent: outbound email interactions linked to this campaign
    - opens:       email_open engagement events for leads in this campaign
    - clicks:      email_click (or click) engagement events for leads in this campaign
    - unsubscribes: opt_out engagement events on email channel for these leads
    """
    # Verify the campaign belongs to this company.
    campaign = session.exec(
        select(Campaign).where(Campaign.id == campaign_id, Campaign.company_id == company_id)
    ).first()
    if not campaign:
        return {"error": "Campaign not found"}

    # Lead IDs enrolled in this campaign.
    enrolled_lead_ids: list[int] = list(session.exec(
        select(CampaignRecipient.lead_id).where(
            CampaignRecipient.campaign_id == campaign_id,
            CampaignRecipient.company_id == company_id,
        )
    ).all())

    if not enrolled_lead_ids:
        return {
            "campaign_id": campaign_id,
            "campaign_name": campaign.name,
            "emails_sent": 0,
            "opens": 0,
            "clicks": 0,
            "unsubscribes": 0,
            "open_rate": 0.0,
            "click_rate": 0.0,
            "unsubscribe_rate": 0.0,
        }

    # Emails sent via this campaign.
    emails_sent = session.exec(
        select(func.count(Interaction.id)).where(
            Interaction.company_id == company_id,
            Interaction.campaign_id == campaign_id,
            Interaction.channel == "email",
            Interaction.direction == "outbound",
        )
    ).one()

    # Engagement events for enrolled leads scoped to email channel.
    def _event_count(event_types: list[str]) -> int:
        return session.exec(
            select(func.count(EngagementEvent.id)).where(
                EngagementEvent.company_id == company_id,
                EngagementEvent.lead_id.in_(enrolled_lead_ids),  # type: ignore[arg-type]
                EngagementEvent.event_type.in_(event_types),  # type: ignore[arg-type]
            )
        ).one()

    opens = _event_count(["email_open", "open"])
    clicks = _event_count(["email_click", "click"])
    unsubscribes = _event_count(["opt_out", "unsubscribe"])

    base = emails_sent or 0

    def _rate(numerator: int) -> float:
        return round((numerator / base) * 100, 1) if base > 0 else 0.0

    return {
        "campaign_id": campaign_id,
        "campaign_name": campaign.name,
        "campaign_status": campaign.status,
        "emails_sent": base,
        "opens": opens,
        "clicks": clicks,
        "unsubscribes": unsubscribes,
        "open_rate": _rate(opens),
        "click_rate": _rate(clicks),
        "unsubscribe_rate": _rate(unsubscribes),
    }


def get_campaign_drilldown(session: Session, company_id: int, campaign_id: int) -> list[dict]:
    rows = session.exec(
        select(
            func.date(CampaignRecipient.updated_at).label("day"),
            CampaignRecipient.status,
            func.count(CampaignRecipient.id),
        )
        .where(CampaignRecipient.company_id == company_id)
        .where(CampaignRecipient.campaign_id == campaign_id)
        .group_by(func.date(CampaignRecipient.updated_at), CampaignRecipient.status)
        .order_by(func.date(CampaignRecipient.updated_at))
    ).all()
    return [
        {"day": str(row[0]), "status": row[1], "count": row[2]}
        for row in rows
        if row[0] and row[1]
    ]


def get_call_conversion_summary(
    session: Session,
    company_id: int,
    days: int = 30,
    scope_user_id: int | None = None,
) -> dict:
    """
    Returns call-to-outcome conversion rates for a company over the last N days.
    When scope_user_id is set, only counts data owned by / assigned to that user.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)

    call_filters = [
        Interaction.company_id == company_id,
        Interaction.type == "call",
        Interaction.created_at >= since,
    ]
    if scope_user_id:
        call_filters.append(Interaction.user_id == scope_user_id)

    total_calls = session.exec(
        select(func.count(Interaction.id)).where(*call_filters)
    ).one()

    leads_called = session.exec(
        select(func.count(func.distinct(Interaction.lead_id))).where(
            *call_filters, Interaction.lead_id.is_not(None),
        )
    ).one()

    appt_filters = [Appointment.company_id == company_id, Appointment.created_at >= since]
    if scope_user_id:
        appt_filters.append(Appointment.owner_user_id == scope_user_id)
    demos_booked = session.exec(
        select(func.count(Appointment.id)).where(*appt_filters)
    ).one()

    quote_filters = [
        Quote.company_id == company_id,
        Quote.deleted_at.is_(None),
        Quote.status.in_(["sent", "viewed", "accepted", "rejected"]),
        Quote.created_at >= since,
    ]
    if scope_user_id:
        quote_filters.append(Quote.created_by == scope_user_id)
    quotes_sent = session.exec(
        select(func.count(Quote.id)).where(*quote_filters)
    ).one()

    lead_filters = [
        Lead.company_id == company_id,
        Lead.ism_stage == "closed_won",
        Lead.deleted_at.is_(None),
    ]
    if scope_user_id:
        lead_filters.append(Lead.owner_user_id == scope_user_id)
    closed_won = session.exec(
        select(func.count(Lead.id)).where(*lead_filters)
    ).one()

    def _rate(num, denom) -> float:
        return round((num / denom) * 100, 1) if denom else 0.0

    return {
        "period_days": days,
        "total_calls": total_calls or 0,
        "leads_called": leads_called or 0,
        "demos_booked": demos_booked or 0,
        "quotes_sent": quotes_sent or 0,
        "closed_won": closed_won or 0,
        "demo_rate_pct": _rate(demos_booked, total_calls),
        "quote_rate_pct": _rate(quotes_sent, total_calls),
        "close_rate_pct": _rate(closed_won, leads_called),
    }


def get_call_performance_metrics(
    session: Session,
    company_id: int,
    days: int = 30,
    scope_user_id: int | None = None,
) -> dict:
    """
    Call performance metrics for the dashboard Performance tab.
    When scope_user_id is set, only counts data assigned to that user.
    """
    since = utc_now() - timedelta(days=days)

    task_filters = [
        CallTask.company_id == company_id,
        CallTask.completed_at >= since,
        CallTask.last_outcome.is_not(None),
    ]
    if scope_user_id:
        task_filters.append(CallTask.assigned_user_id == scope_user_id)

    outcome_rows = session.exec(
        select(CallTask.last_outcome, func.count(CallTask.id))
        .where(*task_filters)
        .group_by(CallTask.last_outcome)
    ).all()
    outcome_counts: dict[str, int] = {r[0]: r[1] for r in outcome_rows if r[0]}
    total_with_outcome = sum(outcome_counts.values())
    connected = sum(v for k, v in outcome_counts.items() if k and k.startswith("answered_"))

    dur_filters = [
        Interaction.company_id == company_id,
        Interaction.type == "call",
        Interaction.recording_duration > 0,
        Interaction.created_at >= since,
    ]
    if scope_user_id:
        dur_filters.append(Interaction.user_id == scope_user_id)

    avg_duration = session.exec(
        select(func.avg(Interaction.recording_duration)).where(*dur_filters)
    ).one()

    def _rate(num: int, denom: int) -> float:
        return round((num / denom) * 100, 1) if denom else 0.0

    return {
        "period_days": days,
        "connect_rate_pct": _rate(connected, total_with_outcome),
        "avg_talk_time_seconds": round(float(avg_duration or 0)),
        "total_with_outcome": total_with_outcome,
        "connected_calls": connected,
        "outcome_counts": outcome_counts,
    }


def list_alerts(session: Session, company_id: int) -> list[AnalyticsAlert]:
    return session.exec(
        select(AnalyticsAlert).where(AnalyticsAlert.company_id == company_id)
    ).all()


def create_alert(
    session: Session,
    company_id: int,
    metric: str,
    threshold: Decimal,
    direction: str = "gte",
    channel: str = "email",
) -> AnalyticsAlert:
    alert = AnalyticsAlert(
        company_id=company_id,
        metric=metric,
        threshold=threshold,
        direction=direction,
        channel=channel,
    )
    session.add(alert)
    session.commit()
    session.refresh(alert)
    return alert


def evaluate_alerts(session: Session, company_id: int) -> list[dict]:
    since = utc_now() - timedelta(days=1)
    rows = session.exec(
        select(EngagementEvent.event_type, func.count(EngagementEvent.id))
        .where(EngagementEvent.company_id == company_id)
        .where(EngagementEvent.created_at >= since)
        .group_by(EngagementEvent.event_type)
    ).all()
    counts = {row[0]: row[1] for row in rows if row[0]}
    alerts = session.exec(
        select(AnalyticsAlert).where(
            AnalyticsAlert.company_id == company_id, AnalyticsAlert.enabled == True
        )
    ).all()

    triggered = []
    for alert in alerts:
        value = counts.get(alert.metric, 0)
        meets = value >= alert.threshold if alert.direction == "gte" else value <= alert.threshold
        if meets:
            alert.last_triggered_at = utc_now()
            session.add(alert)
            triggered.append(
                {"metric": alert.metric, "value": value, "threshold": float(alert.threshold)}
            )
    session.commit()
    return triggered
