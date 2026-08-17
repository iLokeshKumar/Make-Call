"""ISM Rules CRUD — admin API for the data-driven rules engine.

Endpoints:
  GET    /ism-rules                    — list all rules (with active/priority filters)
  POST   /ism-rules                    — create a new rule
  GET    /ism-rules/{id}               — fetch one rule
  PATCH  /ism-rules/{id}               — update (rename, tweak conditions, re-prioritize)
  DELETE /ism-rules/{id}               — delete (hard; rules don't soft-delete)
  POST   /ism-rules/{id}/toggle        — flip is_active without touching other fields

Permissions:
  - agent.manage : any write
  - agent.review : read-only

All input JSON is validated against the rules engine DSL via the existing
evaluate_rules code path. Unknown operators or verbs are rejected at create/
patch time so bad rules never land in the DB.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from auth import PermissionChecker
from database import get_session
from models.models import IsmRule, User, utc_now
from services.agent.ism_rules_validation import validate_then_action, validate_when_json

router = APIRouter(prefix="/ism-rules", tags=["ISM Rules"])


# Request models

class CreateRuleRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    priority: int = Field(default=10, ge=0, le=9999)
    when_json: dict[str, Any] = Field(default_factory=dict)
    then_action: str
    is_active: bool = True


class UpdateRuleRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    priority: Optional[int] = Field(default=None, ge=0, le=9999)
    when_json: Optional[dict[str, Any]] = None
    then_action: Optional[str] = None
    is_active: Optional[bool] = None


# Routes

@router.get("")
async def list_rules(
    is_active: Optional[bool] = Query(default=None),
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    """List all ISM rules for this company, ordered by priority then id."""
    query = select(IsmRule).where(IsmRule.company_id == current_user.company_id)
    if is_active is not None:
        query = query.where(IsmRule.is_active == is_active)
    query = query.order_by(IsmRule.priority.asc(), IsmRule.id.asc())
    return session.exec(query).all()


@router.post("")
async def create_rule(
    body: CreateRuleRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Create a new ISM rule. Validated against the engine's DSL."""
    validate_when_json(body.when_json)
    validate_then_action(body.then_action)

    rule = IsmRule(
        company_id=current_user.company_id,
        name=body.name,
        description=body.description,
        priority=body.priority,
        when_json=body.when_json,
        then_action=body.then_action,
        is_active=body.is_active,
        created_by=current_user.id,
        updated_by=current_user.id,
    )
    session.add(rule); session.commit(); session.refresh(rule)
    return rule


@router.get("/{rule_id}")
async def get_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.review")),
):
    rule = session.exec(
        select(IsmRule).where(
            IsmRule.id == rule_id,
            IsmRule.company_id == current_user.company_id,
        )
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.patch("/{rule_id}")
async def update_rule(
    rule_id: int,
    body: UpdateRuleRequest,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Update one or more fields. Validates DSL on every write."""
    rule = session.exec(
        select(IsmRule).where(
            IsmRule.id == rule_id,
            IsmRule.company_id == current_user.company_id,
        )
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if body.when_json is not None:
        validate_when_json(body.when_json)
        rule.when_json = body.when_json
    if body.then_action is not None:
        validate_then_action(body.then_action)
        rule.then_action = body.then_action
    if body.name is not None:
        rule.name = body.name
    if body.description is not None:
        rule.description = body.description
    if body.priority is not None:
        rule.priority = body.priority
    if body.is_active is not None:
        rule.is_active = body.is_active

    rule.updated_at = utc_now()
    rule.updated_by = current_user.id
    session.add(rule); session.commit(); session.refresh(rule)
    return rule


@router.delete("/{rule_id}")
async def delete_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    rule = session.exec(
        select(IsmRule).where(
            IsmRule.id == rule_id,
            IsmRule.company_id == current_user.company_id,
        )
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(rule); session.commit()
    return {"deleted": True, "id": rule_id}


@router.post("/{rule_id}/toggle")
async def toggle_rule(
    rule_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("agent.manage")),
):
    """Flip is_active. Convenient shortcut for the admin UI's toggle switch."""
    rule = session.exec(
        select(IsmRule).where(
            IsmRule.id == rule_id,
            IsmRule.company_id == current_user.company_id,
        )
    ).first()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.is_active = not rule.is_active
    rule.updated_at = utc_now()
    rule.updated_by = current_user.id
    session.add(rule); session.commit(); session.refresh(rule)
    return rule
