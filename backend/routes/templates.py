from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import MessageTemplate, TemplateCreate, TemplateRenderRequest, User
from services.message_render_service import render_template_by_id


router = APIRouter(prefix="/templates", tags=["Templates"])


@router.post("")
async def create_template_route(
    data: TemplateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.manage")),
):
    template = MessageTemplate(
        company_id=current_user.company_id,
        channel=data.channel,
        name=data.name,
        subject_template=data.subject_template,
        body_template=data.body_template,
        variables_schema=data.variables_schema,
        is_active=True,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(template)
    session.commit()
    session.refresh(template)
    return template


@router.get("")
async def list_templates_route(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    return session.exec(
        select(MessageTemplate).where(
            MessageTemplate.company_id == current_user.company_id
        ).order_by(MessageTemplate.created_at.desc())
    ).all()


@router.post("/{template_id}/render")
async def render_template_route(
    template_id: int,
    data: TemplateRenderRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("campaign.read")),
):
    try:
        return render_template_by_id(
            session=session,
            company_id=current_user.company_id,
            template_id=template_id,
            lead_id=data.lead_id,
            quote_id=data.quote_id,
            product_id=data.product_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))