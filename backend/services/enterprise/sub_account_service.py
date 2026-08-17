"""Sub-account lifecycle, aggregated usage, concurrency enforcement."""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import HTTPException
from sqlmodel import Session, select, func

from models.models import Company, CompanyUsage

logger = logging.getLogger(__name__)


# ── Sub-Account CRUD ──


def create_sub_account(
    session: Session,
    parent_company_id: int,
    actor_user_id: int,
    name: str,
    slug: str,
    subscription_tier: str = "starter",
    max_users: int = 3,
    max_concurrent_calls: int = 2,
    daily_call_cap: int | None = None,
    routing_region: str = "global",
) -> Company:
    parent = session.get(Company, parent_company_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Parent company not found")

    existing = session.exec(select(Company).where(Company.slug == slug)).first()
    if existing:
        raise HTTPException(status_code=400, detail="Slug already taken")

    child = Company(
        name=name,
        slug=slug,
        parent_id=parent_company_id,
        status="active",
        subscription_tier=subscription_tier,
        max_users=max_users,
        max_concurrent_calls=max_concurrent_calls,
        daily_call_cap=daily_call_cap,
        routing_region=routing_region,
    )
    session.add(child)
    session.commit()
    session.refresh(child)
    logger.info("Sub-account %s (id=%d) created under parent %d", name, child.id, parent_company_id)
    return child


def list_sub_accounts(session: Session, parent_company_id: int) -> list[Company]:
    return session.exec(
        select(Company).where(Company.parent_id == parent_company_id)
    ).all()


def get_sub_account(session: Session, parent_company_id: int, sub_id: int) -> Company:
    child = session.get(Company, sub_id)
    if not child or child.parent_id != parent_company_id:
        raise HTTPException(status_code=404, detail="Sub-account not found")
    return child


def update_sub_account(
    session: Session,
    parent_company_id: int,
    sub_id: int,
    actor_user_id: int,
    **updates,
) -> Company:
    child = get_sub_account(session, parent_company_id, sub_id)
    allowed = {"max_concurrent_calls", "daily_call_cap", "max_users", "subscription_tier", "status", "routing_region"}
    for key, value in updates.items():
        if key in allowed and value is not None:
            setattr(child, key, value)
    child.updated_by = actor_user_id
    session.add(child)
    session.commit()
    session.refresh(child)
    return child


def delete_sub_account(session: Session, parent_company_id: int, sub_id: int) -> None:
    child = get_sub_account(session, parent_company_id, sub_id)
    child.status = "disabled"
    child.updated_by = 0
    session.add(child)
    session.commit()


# ── Aggregated Usage ──


def get_aggregated_usage(
    session: Session,
    parent_company_id: int,
    month: str | None = None,
) -> dict:
    if not month:
        import datetime
        month = datetime.datetime.utcnow().strftime("%Y-%m")

    sub_ids = [
        row[0]
        for row in session.exec(
            select(Company.id).where(Company.parent_id == parent_company_id)
        ).all()
    ]

    if not sub_ids:
        return {"month": month, "sub_accounts": [], "totals": {}}

    rows = session.exec(
        select(CompanyUsage).where(
            CompanyUsage.company_id.in_(sub_ids),
            CompanyUsage.month == month,
        )
    ).all()

    per_sub: dict[int, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for row in rows:
        per_sub.setdefault(row.company_id, {})[row.metric] = row.count
        totals[row.metric] = totals.get(row.metric, 0) + row.count

    children = {
        c.id: c
        for c in session.exec(
            select(Company).where(Company.id.in_(sub_ids))
        ).all()
    }

    sub_summaries = []
    for sid in sub_ids:
        child = children.get(sid)
        metrics = per_sub.get(sid, {})
        sub_summaries.append({
            "id": sid,
            "name": child.name if child else "?",
            "status": child.status if child else "?",
            "max_concurrent_calls": child.max_concurrent_calls if child else 0,
            "daily_call_cap": child.daily_call_cap if child else None,
            "usage": metrics,
        })

    return {
        "month": month,
        "sub_accounts": sub_summaries,
        "totals": totals,
    }


# ── Concurrency / Capacity Enforcement ──


def get_active_call_count(session: Session, company_id: int) -> int:
    from models.models import CallTask
    return session.exec(
        select(func.count(CallTask.id)).where(
            CallTask.company_id == company_id,
            CallTask.status.in_(["in_progress", "ringing", "queued"]),
        )
    ).one()


def check_concurrency_limit(session: Session, company_id: int) -> tuple[bool, str | None]:
    company = session.get(Company, company_id)
    if not company:
        return False, "company_not_found"
    active = get_active_call_count(session, company_id)
    if active >= company.max_concurrent_calls:
        return False, f"max_concurrent_calls_reached ({active}/{company.max_concurrent_calls})"
    return True, None


def check_daily_call_cap(session: Session, company_id: int) -> tuple[bool, str | None]:
    company = session.get(Company, company_id)
    if not company or company.daily_call_cap is None:
        return True, None
    import datetime
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    from models.models import CallTask
    today_count = session.exec(
        select(func.count(CallTask.id)).where(
            CallTask.company_id == company_id,
            func.date(CallTask.created_at) == today,
        )
    ).one()
    if today_count >= company.daily_call_cap:
        return False, f"daily_call_cap_reached ({today_count}/{company.daily_call_cap})"
    return True, None
