from __future__ import annotations

import asyncio
import logging
from typing import Optional

from database import engine, rls_company_id
from schemas.tool_result import ToolResult
from sqlmodel import Session, select

logger = logging.getLogger(__name__)


def _run_sync(company_id: int, fn, *args, **kwargs):
    token = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            return fn(session, company_id, *args, **kwargs)
    finally:
        rls_company_id.reset(token)


def _contact_to_dict(c) -> dict:
    return {
        "contact_id": c.id,
        "name": c.name,
        "email": c.email,
        "phone": c.phone,
        "role": c.designation,
        "department": c.department,
        "is_primary": c.is_primary,
        "is_active": c.is_active,
        "lead_id": c.lead_id,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


async def create_contact(
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    name: str,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    designation: Optional[str] = None,
    department: Optional[str] = None,
    is_primary: bool = False,
) -> dict:
    from models.models import ContactCreate
    from services.contact.contact_service import create_contact as _create
    try:
        data = ContactCreate(
            lead_id=lead_id,
            name=name,
            email=email,
            phone=phone,
            designation=designation,
            department=department,
            is_primary=is_primary,
        )

        def _q(session, cid):
            return _create(session, cid, actor_user_id, data)

        contact = await asyncio.to_thread(_run_sync, company_id, _q)
        return ToolResult.ok(_contact_to_dict(contact)).model_dump()
    except Exception as exc:
        logger.error("[contacts] create_contact failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def list_contacts(
    company_id: int,
    lead_id: int,
) -> dict:
    from services.contact.contact_service import list_contacts as _list
    try:
        def _q(session, cid):
            return _list(session, cid, lead_id=lead_id)

        contacts = await asyncio.to_thread(_run_sync, company_id, _q)
        return ToolResult.ok([_contact_to_dict(c) for c in contacts]).model_dump()
    except Exception as exc:
        logger.error("[contacts] list_contacts failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()
