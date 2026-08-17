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


async def get_lead_requirements(company_id: int, lead_id: int) -> dict:
    from services.requirement_service import get_latest_requirements
    try:
        def _q(session, cid):
            return get_latest_requirements(session, cid, lead_id)
        req = await asyncio.to_thread(_run_sync, company_id, _q)
        if req is None:
            return ToolResult.ok(None).model_dump()
        return ToolResult.ok({
            "lead_id": req.lead_id,
            "use_case": req.use_case,
            "budget_range": req.budget_range,
            "timeline": req.timeline,
            "decision_maker": req.decision_maker,
            "pain_points": req.pain_points,
            "competitors": req.competitors,
            "required_products": req.required_products,
            "notes": req.notes,
            "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        }).model_dump()
    except Exception as exc:
        logger.error("[post_call] get_lead_requirements failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def upsert_lead_requirements(
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    use_case: Optional[str] = None,
    budget_range: Optional[str] = None,
    timeline: Optional[str] = None,
    decision_maker: Optional[str] = None,
    pain_points: Optional[str] = None,
    competitors: Optional[str] = None,
    required_products: Optional[str] = None,
    notes: Optional[str] = None,
) -> dict:
    from models.models import LeadRequirementUpsert
    from services.requirement_service import upsert_lead_requirements as _upsert
    try:
        data = LeadRequirementUpsert(
            lead_id=lead_id,
            use_case=use_case,
            budget_range=budget_range,
            timeline=timeline,
            decision_maker=decision_maker,
            pain_points=pain_points,
            competitors=competitors,
            required_products=required_products,
            notes=notes,
        )

        def _q(session, cid):
            return _upsert(session, cid, actor_user_id, data)

        req = await asyncio.to_thread(_run_sync, company_id, _q)
        return ToolResult.ok({
            "lead_id": req.lead_id,
            "requirements_id": req.id,
            "updated_at": req.updated_at.isoformat() if req.updated_at else None,
        }).model_dump()
    except Exception as exc:
        logger.error("[post_call] upsert_lead_requirements failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def send_csat(
    company_id: int,
    lead_id: int,
    actor_user_id: int,
    interaction_id: Optional[int] = None,
) -> dict:
    from services.feedback.csat_service import get_or_create_pending_csat, get_csat_base_url
    try:
        def _q():
            token = rls_company_id.set(company_id)
            try:
                with Session(engine) as session:
                    return get_or_create_pending_csat(
                        session,
                        company_id=company_id,
                        lead_id=lead_id,
                        actor_user_id=actor_user_id,
                        interaction_id=interaction_id,
                    )
            finally:
                rls_company_id.reset(token)

        fb, is_new = await asyncio.to_thread(_q)
        base = get_csat_base_url()
        return ToolResult.ok({
            "csat_id": fb.id,
            "survey_url": f"{base}/feedback/{fb.token}",
            "expires_at": fb.token_expires_at.isoformat() if fb.token_expires_at else None,
            "is_duplicate": not is_new,
        }).model_dump()
    except Exception as exc:
        logger.error("[post_call] send_csat failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def create_ticket(
    company_id: int,
    actor_user_id: int,
    lead_id: int,
    title: str,
    description: Optional[str] = None,
    priority: str = "medium",
    category: Optional[str] = None,
    sla_hours: int = 24,
) -> dict:
    from models.models import ServiceTicketCreate
    from services.service.ticket_service import create_ticket as _create
    try:
        data = ServiceTicketCreate(
            lead_id=lead_id,
            title=title,
            description=description,
            priority=priority,
            category=category,
            sla_hours=sla_hours,
            channel="voice",
        )

        def _q(session, cid):
            return _create(session, cid, actor_user_id, data)

        ticket = await asyncio.to_thread(_run_sync, company_id, _q)
        return ToolResult.ok({
            "ticket_id": ticket.id,
            "ticket_number": ticket.ticket_number,
            "status": ticket.status,
            "priority": ticket.priority,
            "sla_due_at": ticket.sla_due_at.isoformat() if ticket.sla_due_at else None,
        }).model_dump()
    except Exception as exc:
        logger.error("[post_call] create_ticket failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def list_tickets(company_id: int, lead_id: int) -> dict:
    from services.service.ticket_service import list_tickets as _list
    try:
        def _q(session, cid):
            return _list(session, cid, lead_id=lead_id)

        tickets = await asyncio.to_thread(_run_sync, company_id, _q)
        return ToolResult.ok([
            {
                "ticket_id": t.id,
                "ticket_number": t.ticket_number,
                "title": t.title,
                "status": t.status,
                "priority": t.priority,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "sla_due_at": t.sla_due_at.isoformat() if t.sla_due_at else None,
            }
            for t in tickets
        ]).model_dump()
    except Exception as exc:
        logger.error("[post_call] list_tickets failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()


async def set_next_action(
    company_id: int,
    lead_id: int,
    next_action: str,
    next_action_due_at: Optional[str] = None,
    actor_user_id: Optional[int] = None,
) -> dict:
    from models.models import Lead, utc_now
    from datetime import datetime, timezone
    try:
        due = None
        if next_action_due_at:
            due = datetime.fromisoformat(next_action_due_at.replace("Z", "+00:00"))

        def _q(session, cid):
            from sqlmodel import select as _select
            lead = session.exec(
                _select(Lead).where(Lead.id == lead_id, Lead.company_id == cid)
            ).first()
            if not lead:
                raise ValueError(f"Lead {lead_id} not found")
            lead.next_action = next_action
            if due:
                lead.next_action_due_at = due
            lead.updated_at = utc_now()
            if actor_user_id:
                lead.updated_by = actor_user_id
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return lead

        lead = await asyncio.to_thread(_run_sync, company_id, _q)
        return ToolResult.ok({
            "lead_id": lead.id,
            "next_action": lead.next_action,
            "next_action_due_at": lead.next_action_due_at.isoformat() if lead.next_action_due_at else None,
            "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        }).model_dump()
    except Exception as exc:
        logger.error("[post_call] set_next_action failed: %s", exc)
        return ToolResult.fail(str(exc)).model_dump()
