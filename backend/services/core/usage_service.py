"""
Per-company usage metering.

Usage
-----
    from services.usage_service import check_and_increment, get_usage_summary

    # Before a billable action — raises QuotaExceededError if over limit:
    check_and_increment(session, company_id, "calls_made")

    # Read current month totals (for dashboard):
    summary = get_usage_summary(session, company_id)

    # Check if a metric is available without raising (for channel selection):
    if is_metric_available(session, company_id, "whatsapp_sent"):
        ...
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, select

from models.models import Company, CompanySetting, CompanyUsage, utc_now

logger = logging.getLogger(__name__)


class QuotaExceededError(Exception):
    """Raised when a company has exhausted its plan limit for a metric.

    Attributes:
        metric:     The metered action (e.g. 'calls_made', 'whatsapp_sent')
        used:       Current usage count
        limit:      Plan limit (0 means blocked entirely)
        tier:       Subscription tier name
        message:    Human-readable explanation
    """
    def __init__(
        self,
        metric: str,
        used: int,
        limit: int,
        tier: str,
        *,
        message: str | None = None,
    ) -> None:
        self.metric = metric
        self.used = used
        self.limit = limit
        self.tier = tier
        if message is None:
            label = metric.replace("_", " ").title()
            if limit == 0:
                message = (
                    f"{label} is not included in the '{tier}' plan "
                    f"(0 messages/mo included). Please upgrade to use this feature."
                )
            else:
                message = (
                    f"Monthly {label} limit reached ({used}/{limit}) "
                    f"on the '{tier}' plan. Resets at month-end, or upgrade "
                    f"to increase your limit."
                )
        self.message = message
        super().__init__(self.message)


# ── Tier defaults (fallback when no per-company override exists) ──────────────
# To override for a specific company, insert a CompanySetting row with key
# `usage_limit_<metric>` (e.g. `usage_limit_whatsapp_sent`) and an integer value.
# None  = unlimited
# 0     = feature fully blocked at the plan level

_PLAN_LIMITS: dict[str, dict[str, Optional[int]]] = {
    "starter": {
        "calls_made":     100,
        "emails_sent":    500,
        "whatsapp_sent":  1_000,
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

# CompanySetting key prefix for per-company usage limit overrides.
# Full key: usage_limit_calls_made, usage_limit_emails_sent, usage_limit_whatsapp_sent
_USAGE_LIMIT_SETTING_PREFIX = "usage_limit_"


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
    """Return the effective limit for this company + metric.

    Resolution order:
      1. Per-company override via CompanySetting (key: `usage_limit_<metric>`).
         Set it to an integer string, or "unlimited", or "0" to block.
      2. Tier default from `_PLAN_LIMITS` dict.

    This means an admin can set `usage_limit_whatsapp_sent=500` for a specific
    company without touching code or running a migration.
    """
    # 1. Check for per-company override in CompanySetting
    setting_key = f"{_USAGE_LIMIT_SETTING_PREFIX}{metric}"
    setting = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == setting_key,
        )
    ).first()
    if setting is not None:
        raw = setting.value.strip().lower()
        if raw in ("unlimited", "none", ""):
            return None
        try:
            return int(raw)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid usage limit value for company=%s key=%s value=%r — falling back to tier default",
                company_id, setting_key, setting.value,
            )

    # 2. Fall back to tier default
    company = session.get(Company, company_id)
    tier = (company.subscription_tier if company else "starter").lower()
    limits = _PLAN_LIMITS.get(tier, _PLAN_LIMITS["enterprise"])
    return limits.get(metric, None)


def is_metric_available(session: Session, company_id: int, metric: str) -> bool:
    """Return True if the company's plan allows this metric (before consuming).

    Use this in channel-selection logic (e.g. _pick_channel) to skip
    channels that are blocked by plan limits before attempting dispatch.
    Never raises — pure predicate.
    """
    limit = _get_plan_limit(session, company_id, metric)
    if limit is None:
        return True
    if limit == 0:
        return False
    current = get_usage(session, company_id, metric)
    return current < limit


def check_quota(session: Session, company_id: int, metric: str) -> None:
    """
    Raise QuotaExceededError if the company has exhausted its monthly limit.
    Does NOT increment — call increment_usage separately after success.
    """
    limit = _get_plan_limit(session, company_id, metric)
    if limit is None:
        return  # unlimited
    if limit == 0:
        company = session.get(Company, company_id)
        tier = (company.subscription_tier if company else "starter").lower()
        raise QuotaExceededError(
            metric=metric,
            used=0,
            limit=0,
            tier=tier,
        )

    current = get_usage(session, company_id, metric)
    if current >= limit:
        company = session.get(Company, company_id)
        tier = (company.subscription_tier if company else "starter").lower()
        raise QuotaExceededError(
            metric=metric,
            used=current,
            limit=limit,
            tier=tier,
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
        limit = _get_plan_limit(session, company_id, metric)
        metrics[metric] = {
            "used":  used,
            "limit": limit,
            "pct":   round((used / limit) * 100, 1) if limit and limit > 0 else None,
        }

    return {"month": m, "tier": tier, "metrics": metrics}
