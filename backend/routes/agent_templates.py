import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from auth import get_current_user
from database import get_session
from models.models import AgentTemplateCreate, AgentTemplateUpdate, User
from services.agent.template_service import (
    create_template, delete_template, deploy_template, get_template,
    list_templates, seed_templates_from_directory, update_template,
)

router = APIRouter(prefix="/crm/agent-templates", tags=["Agent Templates"])
logger = logging.getLogger(__name__)


@router.get("")
def list_all(
    category: Optional[str] = Query(None),
    industry: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    return list_templates(session, category=category, industry=industry)


@router.post("", status_code=201)
def create(
    body: AgentTemplateCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        return create_template(session, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{template_id}")
def get_one(
    template_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tmpl = get_template(session, template_id)
    if not tmpl:
        raise HTTPException(status_code=404)
    return tmpl


@router.put("/{template_id}")
def update_one(
    template_id: int,
    body: AgentTemplateUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    tmpl = update_template(session, template_id, body)
    if not tmpl:
        raise HTTPException(status_code=404)
    return tmpl


@router.delete("/{template_id}")
def delete_one(
    template_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    if not delete_template(session, template_id):
        raise HTTPException(status_code=404)
    return {"ok": True}


@router.post("/{template_id}/deploy", status_code=201)
def deploy_one(
    template_id: int,
    agent_name: Optional[str] = Query(None),
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    try:
        agent = deploy_template(session, current_user.company_id, current_user.id, template_id, agent_name=agent_name)
        return {"agent_id": agent.id, "agent_name": agent.name, "status": "deployed"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/seed", status_code=200)
def seed_templates(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    count = seed_templates_from_directory(session)
    return {"seeded": count}
