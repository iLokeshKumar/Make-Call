from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import LeadRequirement, LeadRequirementUpsert, User, utc_now
from services.requirement_service import get_latest_requirements, upsert_lead_requirements


router = APIRouter(prefix="/requirements", tags=["Requirements"])


@router.get("/{lead_id}")
async def get_requirements_route(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.read")),
):
    return get_latest_requirements(session, current_user.company_id, lead_id)


@router.get("/{lead_id}/all")
async def list_requirements_route(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.read")),
):
    """Return all requirement versions for a lead (history), newest first."""
    rows = session.exec(
        select(LeadRequirement).where(
            LeadRequirement.company_id == current_user.company_id,
            LeadRequirement.lead_id == lead_id,
        ).order_by(LeadRequirement.created_at.desc())
    ).all()
    return rows


@router.post("/{lead_id}")
async def create_requirements_route(
    lead_id: int,
    data: LeadRequirementUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.manage")),
):
    """Create or update requirements for a lead (upsert)."""
    data.lead_id = lead_id
    return upsert_lead_requirements(session, current_user.company_id, current_user.id, data)


@router.put("/{lead_id}")
async def upsert_requirements_route(
    lead_id: int,
    data: LeadRequirementUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.manage")),
):
    data.lead_id = lead_id
    return upsert_lead_requirements(session, current_user.company_id, current_user.id, data)


@router.delete("/{lead_id}")
async def delete_requirements_route(
    lead_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.manage")),
):
    """Delete all requirement records for a lead."""
    rows = session.exec(
        select(LeadRequirement).where(
            LeadRequirement.company_id == current_user.company_id,
            LeadRequirement.lead_id == lead_id,
        )
    ).all()
    if not rows:
        raise HTTPException(status_code=404, detail="No requirements found for this lead")
    for row in rows:
        session.delete(row)
    session.commit()
    return {"deleted": len(rows), "lead_id": lead_id}


@router.delete("/{lead_id}/history/{requirement_id}")
async def delete_single_requirement_route(
    lead_id: int,
    requirement_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("requirements.manage")),
):
    """Delete a specific requirement record by ID."""
    row = session.exec(
        select(LeadRequirement).where(
            LeadRequirement.id == requirement_id,
            LeadRequirement.company_id == current_user.company_id,
            LeadRequirement.lead_id == lead_id,
        )
    ).first()
    if not row:
        raise HTTPException(status_code=404, detail="Requirement not found")
    session.delete(row)
    session.commit()
    return {"deleted": True, "requirement_id": requirement_id}