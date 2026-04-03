from datetime import timedelta
from decimal import Decimal

from sqlalchemy import case
from sqlmodel import Session, select, func

from models.models import AnalyticsAlert, EngagementEvent, CallTask, Campaign, CampaignRecipient, Quote, utc_now


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


def get_engagement_summary(session: Session, company_id: int, lookback_days: int = 30) -> dict:
    since = utc_now() - timedelta(days=lookback_days)

    event_rows = session.exec(
        select(EngagementEvent.event_type, func.count(EngagementEvent.id))
        .where(EngagementEvent.company_id == company_id)
        .where(EngagementEvent.created_at >= since)
        .group_by(EngagementEvent.event_type)
    ).all()
    event_counts = {row[0]: row[1] for row in event_rows if row[0]}

    channel_rows = session.exec(
        select(EngagementEvent.channel, func.count(EngagementEvent.id))
        .where(EngagementEvent.company_id == company_id)
        .where(EngagementEvent.created_at >= since)
        .group_by(EngagementEvent.channel)
    ).all()
    channel_counts = {row[0]: row[1] for row in channel_rows if row[0]}

    timeline_rows = session.exec(
        select(
            func.date(EngagementEvent.created_at).label("day"),
            EngagementEvent.event_type,
            func.count(EngagementEvent.id),
        )
        .where(EngagementEvent.company_id == company_id)
        .where(EngagementEvent.created_at >= since)
        .group_by(func.date(EngagementEvent.created_at), EngagementEvent.event_type)
        .order_by(func.date(EngagementEvent.created_at))
    ).all()
    timeline = [
        {"day": str(row[0]), "event_type": row[1], "count": row[2]}
        for row in timeline_rows
        if row[0] and row[1]
    ]

    quote_status_counts = _query_counts(session, company_id, Quote, Quote.status)
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
        .where(CampaignRecipient.updated_at >= since)
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
        .where(Quote.company_id == company_id)
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
        .where(Quote.company_id == company_id)
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
