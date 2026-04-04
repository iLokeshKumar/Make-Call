from datetime import timedelta
from decimal import Decimal

from sqlalchemy import case
from sqlmodel import Session, select, func

from models.models import AnalyticsAlert, EngagementEvent, CallTask, Campaign, CampaignRecipient, Interaction, Quote, utc_now


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
