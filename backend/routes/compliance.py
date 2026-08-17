"""India DLT compliance and Truecaller routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from auth import get_current_active_user, PermissionChecker
from database import get_session
from models.models import User
from services.compliance.compliance_service import (
    create_application,
    list_applications,
    get_application,
    submit_application,
    update_application_status,
    verify_with_truecaller,
)

router = APIRouter(prefix="/crm/compliance", tags=["compliance"])


class ApplicationCreate(BaseModel):
    application_type: str        # dlt_140 | dlt_160 | truecaller_verification
    provider: str                # twilio | plivo | exotel | vobiz
    entity_name: str
    entity_id: str | None = None
    header_id: str | None = None
    template_id: str | None = None
    notes: str | None = None


class ApplicationSubmit(BaseModel):
    document_urls: dict | None = None


class ApplicationStatusUpdate(BaseModel):
    status: str
    notes: str | None = None


class TruecallerVerify(BaseModel):
    phone: str
    business_name: str


@router.post("/applications")
async def api_create_application(
    data: ApplicationCreate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    app = create_application(
        session=session,
        company_id=current_user.company_id,
        actor_user_id=current_user.id,
        application_type=data.application_type,
        provider=data.provider,
        entity_name=data.entity_name,
        entity_id=data.entity_id,
        header_id=data.header_id,
        template_id=data.template_id,
        notes=data.notes,
    )
    return {"id": app.id, "application_type": app.application_type, "status": app.status}


@router.get("/applications")
async def api_list_applications(
    status: str | None = None,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    apps = list_applications(session, current_user.company_id, status_filter=status)
    return [
        {
            "id": a.id,
            "application_type": a.application_type,
            "status": a.status,
            "provider": a.provider,
            "entity_name": a.entity_name,
            "entity_id": a.entity_id,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in apps
    ]


@router.get("/applications/{app_id}")
async def api_get_application(
    app_id: int,
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    app = get_application(session, current_user.company_id, app_id)
    return {
        "id": app.id,
        "application_type": app.application_type,
        "status": app.status,
        "provider": app.provider,
        "entity_name": app.entity_name,
        "entity_id": app.entity_id,
        "header_id": app.header_id,
        "template_id": app.template_id,
        "document_urls": app.document_urls,
        "notes": app.notes,
        "submitted_at": app.submitted_at.isoformat() if app.submitted_at else None,
        "approved_at": app.approved_at.isoformat() if app.approved_at else None,
    }


@router.post("/applications/{app_id}/submit")
async def api_submit_application(
    app_id: int,
    data: ApplicationSubmit,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    app = submit_application(
        session=session,
        company_id=current_user.company_id,
        app_id=app_id,
        actor_user_id=current_user.id,
        document_urls=data.document_urls,
    )
    return {"id": app.id, "status": app.status}


@router.patch("/applications/{app_id}/status")
async def api_update_application_status(
    app_id: int,
    data: ApplicationStatusUpdate,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    app = update_application_status(
        session=session,
        company_id=current_user.company_id,
        app_id=app_id,
        status=data.status,
        actor_user_id=current_user.id,
        notes=data.notes,
    )
    return {"id": app.id, "status": app.status}


@router.post("/truecaller/verify")
async def api_truecaller_verify(
    data: TruecallerVerify,
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
    session: Session = Depends(get_session),
):
    result = verify_with_truecaller(
        session=session,
        company_id=current_user.company_id,
        phone=data.phone,
        business_name=data.business_name,
    )
    return result
