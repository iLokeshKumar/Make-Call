"""
capabilities.py - Executors for connector-backed capability tools.

Each executor forwards the call to services.mcp.capability_router.route_capability(),
which resolves the best connected MCP server/tool for the capability and provider
(including cross-provider failover). A fresh DB session is opened with the correct
RLS company context, matching the pattern used by the other executors.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

async def _route_capability(
    capability: str,
    company_id: int,
    actor_user_id: int,
    arguments: dict,
) -> dict:
    from database import engine, rls_company_id
    from services.mcp.capability_router import route_capability
    from sqlmodel import Session

    token = rls_company_id.set(company_id)
    try:
        with Session(engine) as session:
            return await route_capability(
                session=session,
                company_id=company_id,
                capability=capability,
                arguments=arguments or {},
                user_id=actor_user_id or 0,
            )
    except Exception as exc:
        logger.error("[capabilities] %s failed for company %s: %s", capability, company_id, exc)
        return {"error": f"{capability} failed: {exc}", "capability": capability}
    finally:
        rls_company_id.reset(token)


async def search_prospects(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("search_prospects", company_id, actor_user_id, arguments)


async def enrich_prospect(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("enrich_prospect", company_id, actor_user_id, arguments)


async def create_crm_contact(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("create_crm_contact", company_id, actor_user_id, arguments)


async def update_crm_contact(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("update_crm_contact", company_id, actor_user_id, arguments)


async def crm_query(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("crm_query", company_id, actor_user_id, arguments)


async def enroll_sequence(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("enroll_sequence", company_id, actor_user_id, arguments)


async def outreach_analytics(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("outreach_analytics", company_id, actor_user_id, arguments)


async def inventory_lookup(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("inventory_lookup", company_id, actor_user_id, arguments)


async def inventory_reserve(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("inventory_reserve", company_id, actor_user_id, arguments)


async def schedule_meeting(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("schedule_meeting", company_id, actor_user_id, arguments)


async def get_availability(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("get_availability", company_id, actor_user_id, arguments)


async def list_bookings(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("list_bookings", company_id, actor_user_id, arguments)


async def reschedule_meeting(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("reschedule_meeting", company_id, actor_user_id, arguments)


async def cancel_meeting(company_id: int, actor_user_id: int = 0, **arguments) -> dict:
    return await _route_capability("cancel_meeting", company_id, actor_user_id, arguments)
