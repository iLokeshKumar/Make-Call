from __future__ import annotations

import asyncio
import logging

from database import engine, rls_company_id
from models.models import Lead, utc_now
from schemas.tool_result import ToolResult
from sqlmodel import Session, select

logger = logging.getLogger(__name__)


def _lead_to_dict(lead: Lead) -> dict:
    return {
        "lead_id": lead.id,
        "name": lead.name,
        "phone": lead.normalized_phone,
        "email": lead.email,
        "status": lead.status,
        "ism_stage": lead.ism_stage,
        "company_name": lead.company_name,
        "job_title": lead.job_title,
        "owner_user_id": lead.owner_user_id,
        "product_interest": lead.product_interest,
        "budget_range": lead.budget_range,
        "timeline": lead.timeline,
        "next_action": lead.next_action,
        "lead_score": float(lead.lead_score) if lead.lead_score is not None else None,
        "source": lead.source,
    }


async def get_or_create_lead(
    company_id: int,
    phone: str | None = None,
    email: str | None = None,
    name: str = "Unknown",
    owner_user_id: int | None = None,
) -> dict:
    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                lead = None
                if phone:
                    normalized = phone.strip().replace(" ", "").replace("-", "")
                    lead = session.exec(
                        select(Lead).where(
                            Lead.company_id == company_id,
                            Lead.normalized_phone == normalized,
                            Lead.deleted_at.is_(None),
                        )
                    ).first()
                if lead is None and email:
                    lead = session.exec(
                        select(Lead).where(
                            Lead.company_id == company_id,
                            Lead.email == email,
                            Lead.deleted_at.is_(None),
                        )
                    ).first()

                created = False
                if lead is None:
                    normalized_phone = (phone or "").strip().replace(" ", "").replace("-", "") or "unknown"
                    lead = Lead(
                        company_id=company_id,
                        name=name,
                        normalized_phone=normalized_phone,
                        email=email,
                        owner_user_id=owner_user_id,
                        source="mcp_tool",
                    )
                    session.add(lead)
                    session.commit()
                    session.refresh(lead)
                    created = True

                result = _lead_to_dict(lead)
                result["created"] = created
                return result
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_or_create_lead] company=%s phone=%s error=%s", company_id, phone, exc)
        return ToolResult.fail(
            f"Lead lookup/create failed: {exc}",
            next_suggestion="Ensure phone or email is provided.",
        ).model_dump()


async def get_lead_info(lead_id: int, company_id: int) -> dict:
    def _sync() -> dict | None:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                lead = session.exec(
                    select(Lead).where(
                        Lead.id == lead_id,
                        Lead.company_id == company_id,
                        Lead.deleted_at.is_(None),
                    )
                ).first()
                return _lead_to_dict(lead) if lead else None
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        if data is None:
            return ToolResult.fail(
                f"Lead {lead_id} not found.",
                next_suggestion="Use get_or_create_lead with phone/email to find or create the lead.",
            ).model_dump()
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:get_lead_info] lead=%s error=%s", lead_id, exc)
        return ToolResult.fail(f"Lead info fetch failed: {exc}").model_dump()


async def update_lead_status(
    lead_id: int,
    company_id: int,
    new_status: str,
    note: str = "",
) -> dict:
    def _sync() -> dict:
        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                lead = session.exec(
                    select(Lead).where(
                        Lead.id == lead_id,
                        Lead.company_id == company_id,
                        Lead.deleted_at.is_(None),
                    )
                ).first()
                if not lead:
                    raise ValueError(f"Lead {lead_id} not found")
                old_status = lead.status
                lead.status = new_status
                lead.updated_at = utc_now()
                if note:
                    lead.notes = (lead.notes or "") + f"\n[status → {new_status}] {note}".strip()
                session.add(lead)
                session.commit()
                return {
                    "lead_id": lead_id,
                    "old_status": old_status,
                    "new_status": new_status,
                    "updated_at": lead.updated_at.isoformat(),
                }
        finally:
            rls_company_id.reset(token)

    try:
        data = await asyncio.to_thread(_sync)
        return ToolResult.ok(data).model_dump()
    except Exception as exc:
        logger.error("[MCP:update_lead_status] lead=%s error=%s", lead_id, exc)
        return ToolResult.fail(
            f"Status update failed: {exc}",
            next_suggestion="Valid statuses: new, contacted, qualified, proposal, negotiation, won, lost.",
        ).model_dump()
