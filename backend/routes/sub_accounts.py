"""Sub-account management routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from auth import get_current_active_user, PermissionChecker
from database import get_session
from models.models import Company, User
from services.enterprise.sub_account_service import (
    create_sub_account,
    list_sub_accounts,
    get_sub_account,
    update_sub_account,
    delete_sub_account,
    get_aggregated_usage,
    check_concurrency_limit,
    check_daily_call_cap,
)

router = APIRouter(prefix="/crm/sub-accounts", tags=["sub-accounts"])


class SubAccountCreate(BaseModel):
    name: str
    slug: str
    subscription_tier: str = "starter"
    max_users: int = 3
    max_concurrent_calls: int = 2
    daily_call_cap: int | None = None
    routing_region: str = "global"


class SubAccountUpdate(BaseModel):
    name: str | None = None
    max_users: int | None = None
    max_concurrent_calls: int | None = None
    daily_call_cap: int | None = None
    subscription_tier: str | None = None
    status: str | None = None
    routing_region: str | None = None


@router.post("")
async def api_create_sub_account(
    data: SubAccountCreate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    child = create_sub_account(
        session=session,
        parent_company_id=current_user.company_id,
        actor_user_id=current_user.id,
        name=data.name,
        slug=data.slug,
        subscription_tier=data.subscription_tier,
        max_users=data.max_users,
        max_concurrent_calls=data.max_concurrent_calls,
        daily_call_cap=data.daily_call_cap,
        routing_region=data.routing_region,
    )
    return {"id": child.id, "name": child.name, "slug": child.slug}


@router.get("")
async def api_list_sub_accounts(
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    children = list_sub_accounts(session, current_user.company_id)
    return [
        {
            "id": c.id,
            "name": c.name,
            "slug": c.slug,
            "status": c.status,
            "max_concurrent_calls": c.max_concurrent_calls,
            "daily_call_cap": c.daily_call_cap,
            "max_users": c.max_users,
            "subscription_tier": c.subscription_tier,
            "routing_region": c.routing_region,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in children
    ]


@router.get("/{sub_id}")
async def api_get_sub_account(
    sub_id: int,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    child = get_sub_account(session, current_user.company_id, sub_id)
    return {
        "id": child.id,
        "name": child.name,
        "status": child.status,
        "max_concurrent_calls": child.max_concurrent_calls,
        "daily_call_cap": child.daily_call_cap,
        "max_users": child.max_users,
        "subscription_tier": child.subscription_tier,
        "routing_region": child.routing_region,
    }


@router.patch("/{sub_id}")
async def api_update_sub_account(
    sub_id: int,
    data: SubAccountUpdate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    child = update_sub_account(
        session=session,
        parent_company_id=current_user.company_id,
        sub_id=sub_id,
        actor_user_id=current_user.id,
        **data.model_dump(exclude_none=True),
    )
    return {"id": child.id, "status": "updated"}


@router.delete("/{sub_id}")
async def api_delete_sub_account(
    sub_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    delete_sub_account(session, current_user.company_id, sub_id)
    return {"status": "disabled"}


@router.get("/usage/aggregated")
async def api_aggregated_usage(
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    return get_aggregated_usage(session, current_user.company_id)


@router.get("/{sub_id}/concurrency-check")
async def api_check_concurrency(
    sub_id: int,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    ok, reason = check_concurrency_limit(session, sub_id)
    if not ok:
        child = get_sub_account(session, current_user.company_id, sub_id)
        ok, reason = check_concurrency_limit(session, child.id)
    return {"allowed": ok, "reason": reason}


@router.get("/{sub_id}/daily-cap-check")
async def api_check_daily_cap(
    sub_id: int,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    ok, reason = check_daily_call_cap(session, sub_id)
    return {"allowed": ok, "reason": reason}
