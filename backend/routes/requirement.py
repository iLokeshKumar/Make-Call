from fastapi import APIRouter, Depends
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import LeadRequirementUpsert, User
from services.requirement_service import get_latest_requirements, upsert_lead_requirements


router = APIRouter(prefix="/requirements", tags=["Requirements"])


@router.get("/{lead_id}")
async def get_requirements_route(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.read")),
):
    return get_latest_requirements(session, current_user.company_id, lead_id)


@router.put("/{lead_id}")
async def upsert_requirements_route(
    lead_id: int,
    data: LeadRequirementUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.manage")),
):
    data.lead_id = lead_id
    return upsert_lead_requirements(session, current_user.company_id, current_user.id, data)