from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from auth import PermissionChecker
from database import get_session
from models.models import InstallationJobCreate, User
from services.service.installation_service import (
    assign_installer,
    check_prerequisites,
    complete_job,
    create_installation_job,
    get_job_or_404,
    list_jobs,
    update_job_status,
)

router = APIRouter(prefix="/installations", tags=["Installation Jobs"])


class JobStatusBody(BaseModel):
    status: str
    notes: Optional[str] = None


class JobAssignBody(BaseModel):
    user_id: int


class JobCompleteBody(BaseModel):
    completion_notes: Optional[str] = None
    photos_json: Optional[list] = None
    csat_score: Optional[int] = None


@router.post("")
async def create_installation_job_route(
    data: InstallationJobCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.manage")),
):
    return create_installation_job(
        session, current_user.company_id, current_user.id, data
    )


@router.get("")
async def list_jobs_route(
    status: Optional[str] = None,
    order_id: Optional[int] = None,
    assigned_user_id: Optional[int] = None,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.read")),
):
    return list_jobs(
        session,
        current_user.company_id,
        status=status,
        order_id=order_id,
        assigned_user_id=assigned_user_id,
    )


@router.get("/{job_id}")
async def get_job_route(
    job_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.read")),
):
    return get_job_or_404(session, current_user.company_id, job_id)


@router.patch("/{job_id}/status")
async def update_job_status_route(
    job_id: int,
    body: JobStatusBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.manage")),
):
    return update_job_status(
        session,
        current_user.company_id,
        current_user.id,
        job_id,
        body.status,
        body.notes,
    )


@router.patch("/{job_id}/assign")
async def assign_installer_route(
    job_id: int,
    body: JobAssignBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.manage")),
):
    return assign_installer(
        session,
        current_user.company_id,
        current_user.id,
        job_id,
        body.user_id,
    )


@router.get("/{job_id}/prerequisites")
async def check_prerequisites_route(
    job_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.read")),
):
    all_met, unmet = check_prerequisites(session, current_user.company_id, job_id)
    return {"all_met": all_met, "unmet_items": unmet}


@router.post("/{job_id}/complete")
async def complete_job_route(
    job_id: int,
    body: JobCompleteBody,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("installation.manage")),
):
    return complete_job(
        session,
        current_user.company_id,
        current_user.id,
        job_id,
        completion_notes=body.completion_notes,
        photos_json=body.photos_json,
        csat_score=body.csat_score,
    )
