from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP
from sqlmodel import Session, select

from database import engine
from models.models import Appointment, Interaction, Lead, Product, User
from services.agent_tool_service import (
    book_demo as service_book_demo,
    book_meeting as service_book_meeting,
    check_guardrails as service_check_guardrails,
    check_icp_qualification as service_check_icp_qualification,
    get_call_latency_summary as service_get_call_latency_summary,
    get_google_auth_url as service_get_google_auth_url,
    get_or_create_lead as service_get_or_create_lead,
    get_product_info as service_get_product_info,
    send_communication as service_send_communication,
    submit_google_auth_code as service_submit_google_auth_code,
    sync_product_catalog as service_sync_product_catalog,
)

logger = logging.getLogger(__name__)
mcp = FastMCP("Rio CRM Navigator")


def _resolve_user_context(session: Session, user_id: int | None) -> tuple[int | None, int | None]:
    if not user_id:
        return None, None
    user = session.get(User, user_id)
    if not user:
        return None, None
    return user.company_id, user.id


@mcp.resource("crm://leads/{user_id}")
def get_leads_summary(user_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        leads = session.exec(
            select(Lead).where(Lead.company_id == company_id).order_by(Lead.created_at.desc())
        ).all()
        return [
            {
                "id": lead.id,
                "name": lead.name,
                "normalized_phone": lead.normalized_phone,
                "status": lead.status,
                "qualification_status": lead.qualification_status,
                "next_action": lead.next_action,
            }
            for lead in leads[:100]
        ]


@mcp.resource("crm://inventory/{user_id}")
def get_inventory(user_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        products = session.exec(
            select(Product).where(Product.company_id == company_id).order_by(Product.created_at.desc())
        ).all()
        return [
            {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "stock": product.stock,
                "price": str(product.price),
                "currency": product.currency,
                "note": product.note,
            }
            for product in products[:100]
        ]


@mcp.resource("crm://interactions/{user_id}/{lead_id}")
def get_lead_interactions(user_id: int, lead_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        interactions = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead_id,
            ).order_by(Interaction.started_at.desc())
        ).all()
        return [
            {
                "id": item.id,
                "type": item.type,
                "channel": item.channel,
                "direction": item.direction,
                "content": item.content,
                "status": item.status,
                "started_at": item.started_at.isoformat() if item.started_at else None,
            }
            for item in interactions[:50]
        ]


@mcp.resource("crm://appointments/{user_id}")
def get_appointments(user_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        appointments = session.exec(
            select(Appointment).where(Appointment.company_id == company_id).order_by(Appointment.appointment_time.desc())
        ).all()
        return [
            {
                "id": item.id,
                "lead_id": item.lead_id,
                "appointment_time": item.appointment_time.isoformat(),
                "status": item.status,
                "meeting_link": item.meeting_link,
            }
            for item in appointments[:100]
        ]


@mcp.tool()
def check_icp_qualification(company_size: str, industry: str, employee_count: int = 0) -> dict[str, Any]:
    return service_check_icp_qualification(company_size, industry, employee_count)


@mcp.tool()
def get_product_info(product_name: str, user_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        return service_get_product_info(session, company_id, product_name)


@mcp.tool()
def check_guardrails(requested_discount_percent: float) -> dict[str, Any]:
    return service_check_guardrails(requested_discount_percent)


@mcp.tool()
def get_or_create_lead(name: str, phone: str, user_id: int, email: str | None = None) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_get_or_create_lead(session, company_id, actor_user_id, name, phone, email)


@mcp.tool()
async def book_meeting(
    lead_id: int,
    proposed_time: str,
    user_id: int,
    meeting_type: str = "demo",
    lead_email: str | None = None,
) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return await service_book_meeting(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            proposed_time=proposed_time,
            meeting_type=meeting_type,
            lead_email=lead_email,
        )


@mcp.tool()
async def book_demo(
    lead_id: int,
    name: str,
    phone: str,
    demo_date: str,
    products: str,
    user_id: int,
    demo_type: str = "Offline",
    city: str | None = None,
    state: str | None = None,
    pincode: str | None = None,
    email: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return await service_book_demo(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            name=name,
            phone=phone,
            demo_date=demo_date,
            products=products,
            demo_type=demo_type,
            city=city,
            state=state,
            pincode=pincode,
            email=email,
            notes=notes,
        )


@mcp.tool()
def send_communication(
    lead_id: int,
    channels: list[str],
    content: str,
    user_id: int,
    subject: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_send_communication(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            channels=channels,
            content=content,
            subject=subject,
            email=email,
            phone=phone,
        )


@mcp.tool()
def sync_product_catalog(user_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        return service_sync_product_catalog(session, company_id)


@mcp.tool()
def get_call_latency_summary(interaction_id: int) -> dict[str, Any]:
    return service_get_call_latency_summary(interaction_id)


@mcp.tool()
def get_google_auth_url(user_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_get_google_auth_url(session, company_id, actor_user_id)


@mcp.tool()
def submit_google_auth_code(user_id: int, code: str) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_submit_google_auth_code(session, company_id, actor_user_id, code)


if __name__ == "__main__":
    mcp.run()
