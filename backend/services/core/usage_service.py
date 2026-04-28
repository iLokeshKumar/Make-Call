"""
Per-company usage metering.

Usage
-----
    from services.usage_service import check_and_increment, get_usage_summary

    # Before a billable action — raises HTTP 429 if over limit:
    check_and_increment(session, company_id, "calls_made")

    # Read current month totals (for dashboard):
    summary = get_usage_summary(session, company_id)
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from models.models import Company, CompanyUsage, utc_now

logger = logging.getLogger(__name__)

# None  = unlimited
# 0     = feature fully blocked at the usage level (use feature flags instead. if you want a cleaner "not available" message)

PLAN_LIMITS: dict[str, dict[str, Optional[int]]] = {
    "starter": {
        "calls_made":     100,
        "emails_sent":    500,
        "whatsapp_sent":  0,
    },
    "pro": {
        "calls_made":     1_000,
        "emails_sent":    5_000,
        "whatsapp_sent":  1_000,
    },
    "business": {
        "calls_made":     5_000,
        "emails_sent":    20_000,
        "whatsapp_sent":  5_000,
    },
    "enterprise": {
        "calls_made":     None,
        "emails_sent":    None,
        "whatsapp_sent":  None,
    },
}

KNOWN_METRICS = {"calls_made", "emails_sent", "whatsapp_sent"}


def _this_month() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m")


def increment_usage(session: Session, company_id: int, metric: str, by: int = 1) -> int:
    """
    Atomically upsert the usage counter for the current month.
    Returns the new count. Never raises — logs errors silently so a metering
    bug can't block a legitimate action.
    """
    try:
        month = _this_month()
        stmt = (
            pg_insert(CompanyUsage)
            .values(
                company_id=company_id,
                month=month,
                metric=metric,
                count=by,
                updated_at=utc_now(),
            )
            .on_conflict_do_update(
                index_elements=["company_id", "month", "metric"],
                set_={
                    "count": CompanyUsage.count + by,
                    "updated_at": utc_now(),
                },
            )
            .returning(CompanyUsage.count)
        )
        result = session.exec(stmt).scalar()  # type: ignore[arg-type]
        session.commit()
        return result or 0
    except Exception as exc:
        logger.warning("usage increment failed for company=%s metric=%s: %s", company_id, metric, exc)
        return 0


def get_usage(session: Session, company_id: int, metric: str, month: Optional[str] = None) -> int:
    """Return the current count for a company/metric/month."""
    row = session.exec(
        select(CompanyUsage).where(
            CompanyUsage.company_id == company_id,
            CompanyUsage.month == (month or _this_month()),
            CompanyUsage.metric == metric,
        )
    ).first()
    return row.count if row else 0


def _get_plan_limit(session: Session, company_id: int, metric: str) -> Optional[int]:
    company = session.get(Company, company_id)
    tier = (company.subscription_tier if company else "starter").lower()
    limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["enterprise"])
    # Key missing from table → unlimited
    return limits.get(metric, None)


def check_quota(session: Session, company_id: int, metric: str) -> None:
    """
    Raise HTTP 429 if the company has already hit its monthly limit.
    Does NOT increment — call increment_usage separately after success.
    """
    limit = _get_plan_limit(session, company_id, metric)
    if limit is None:
        return  # unlimited

    current = get_usage(session, company_id, metric)
    if current >= limit:
        company = session.get(Company, company_id)
        tier = (company.subscription_tier if company else "starter")
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly {metric.replace('_', ' ')} limit reached "
                f"({current}/{limit}) on the {tier!r} plan. "
                "Please upgrade to continue."
            ),
        )


def check_and_increment(session: Session, company_id: int, metric: str) -> None:
    """
    Convenience wrapper: check quota then increment.
    Call this BEFORE the billable action fires.
    """
    check_quota(session, company_id, metric)
    increment_usage(session, company_id, metric)


def get_usage_summary(session: Session, company_id: int, month: Optional[str] = None) -> dict:
    """
    Return a full summary dict suitable for a dashboard widget.

    {
      "month": "2026-04",
      "tier": "pro",
      "metrics": {
        "calls_made":    {"used": 42,  "limit": 1000, "pct": 4.2},
        "emails_sent":   {"used": 120, "limit": 5000, "pct": 2.4},
        "whatsapp_sent": {"used": 8,   "limit": 1000, "pct": 0.8},
      }
    }
    """
    m = month or _this_month()
    company = session.get(Company, company_id)
    tier = (company.subscription_tier if company else "starter").lower()
    limits = PLAN_LIMITS.get(tier, PLAN_LIMITS["enterprise"])

    rows = session.exec(
        select(CompanyUsage).where(
            CompanyUsage.company_id == company_id,
            CompanyUsage.month == m,
        )
    ).all()
    counts = {r.metric: r.count for r in rows}

    metrics = {}
    for metric in KNOWN_METRICS:
        used  = counts.get(metric, 0)
        limit = limits.get(metric, None)
        metrics[metric] = {
            "used":  used,
            "limit": limit,
            "pct":   round((used / limit) * 100, 1) if limit else None,
        }

    return {"month": m, "tier": tier, "metrics": metrics}
