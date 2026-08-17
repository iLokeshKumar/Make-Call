from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from pydantic import BaseModel

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import ProviderPhoneNumber, User
from services.telephony.phone_number_service import (
    search_available_numbers,
    buy_or_register_number,
    release_number,
    assign_number_to_agent,
)

router = APIRouter(tags=["Phone Numbers"])


class BuyNumberRequest(BaseModel):
    provider: str
    number: str
    friendly_name: Optional[str] = None


class AssignNumberRequest(BaseModel):
    agent_id: Optional[int] = None


@router.get("/phone-numbers")
def list_phone_numbers(
    status: Optional[str] = None,
    provider: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
):
    query = select(ProviderPhoneNumber).where(
        ProviderPhoneNumber.company_id == current_user.company_id,
    )
    if status:
        query = query.where(ProviderPhoneNumber.status == status)
    else:
        query = query.where(ProviderPhoneNumber.status == "active")
    if provider:
        query = query.where(ProviderPhoneNumber.provider == provider)
    query = query.order_by(ProviderPhoneNumber.created_at.desc())
    return session.exec(query).all()


@router.get("/phone-numbers/search")
def search_numbers(
    provider: str,
    country: str = "US",
    area_code: Optional[str] = None,
    limit: int = 20,
    current_user: User = Depends(PermissionChecker("settings.manage")),
    session: Session = Depends(get_session),
):
    return search_available_numbers(
        session=session,
        company_id=current_user.company_id,
        provider=provider,
        country=country,
        area_code=area_code,
        limit=min(limit, 50),
    )


@router.post("/phone-numbers/buy")
def buy_number(
    data: BuyNumberRequest,
    current_user: User = Depends(PermissionChecker("settings.manage")),
    session: Session = Depends(get_session),
):
    return buy_or_register_number(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        provider=data.provider,
        number=data.number,
        friendly_name=data.friendly_name,
    )


@router.delete("/phone-numbers/{number_id}")
def delete_number(
    number_id: int,
    current_user: User = Depends(PermissionChecker("settings.manage")),
    session: Session = Depends(get_session),
):
    release_number(session=session, company_id=current_user.company_id, number_id=number_id)
    return {"status": "released"}


@router.patch("/phone-numbers/{number_id}/assign")
def assign_number(
    number_id: int,
    data: AssignNumberRequest,
    current_user: User = Depends(PermissionChecker("settings.manage")),
    session: Session = Depends(get_session),
):
    return assign_number_to_agent(
        session=session,
        company_id=current_user.company_id,
        number_id=number_id,
        agent_id=data.agent_id,
        actor_user_id=current_user.id,
    )
