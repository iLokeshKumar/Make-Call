"""
capability_router.py - Maps business capabilities to MCP server tools.

Agents call a capability like "search_prospects" or "create_crm_contact".
The router picks the best available server+tool combination based on what's
enabled and healthy in the company's registry, then delegates to connection_service.
"""
from __future__ import annotations

import logging
from typing import Optional

from sqlmodel import Session, select

from models.mcp_server import MCPServer
from services.mcp.registry_service import get_tool_cache

logger = logging.getLogger(__name__)

# "provider.tool_name" entries are tried in order; first match that has an
# enabled MCPServer for this company wins.
CAPABILITY_MAP: dict[str, list[str]] = {
    "search_prospects":     ["apollo.mixed_people_api_search", "apollo.contacts_search", "rocketreach_mcp.person_search"],
    "enrich_prospect":      ["apollo.people_match", "apollo.organizations_enrich", "rocketreach_mcp.person_lookup"],
    "create_crm_contact":   ["zoho.createRecords"],
    "update_crm_contact":   ["zoho.updateRecords"],
    "crm_query":            ["zoho.executeCOQLQuery", "zoho.searchRecords"],
    "enroll_sequence":      ["apollo.emailer_campaigns_add_contact_ids"],
    "outreach_analytics":   ["apollo.analytics_sync_report"],
    "inventory_lookup":     ["inventory.lookup"],
    "inventory_reserve":    ["inventory.reserve"],
    # Scheduling via Cal.com
    "schedule_meeting":     ["calcom.create_booking", "calendly.create_event"],
    "get_availability":     ["calcom.get_availability", "calendly.get_availability"],
    "list_bookings":        ["calcom.get_bookings", "calendly.list_scheduled_events"],
    "reschedule_meeting":   ["calcom.reschedule_booking", "calendly.reschedule_event"],
    "cancel_meeting":       ["calcom.cancel_booking", "calendly.cancel_event"],
}


def get_capabilities() -> list[str]:
    return list(CAPABILITY_MAP.keys())


def _find_server(session: Session, company_id: int, provider: str, tool_name: str) -> Optional[MCPServer]:
    """Find the highest-priority enabled MCPServer for a provider that has the tool."""
    servers = list(session.exec(
        select(MCPServer).where(
            MCPServer.company_id == company_id,
            MCPServer.provider == provider,
            MCPServer.enabled == True,
        ).order_by(MCPServer.priority.desc())
    ).all())

    for server in servers:
        cached = get_tool_cache(session, server.id)
        if cached:
            if any(t.tool_name == tool_name for t in cached):
                return server
        else:
            # No cache yet — return the server so the caller can try anyway
            return server
    return None


def _resolve_token(session: Session, company_id: int, provider: str) -> Optional[str]:
    if provider == "apollo":
        from routes.apollo_oauth import get_company_apollo_token
        return get_company_apollo_token(session, company_id)
    if provider == "zoho":
        from services.mcp.provider_adapters.zoho import get_token as _zoho_token
        return _zoho_token(session, company_id)
    if provider == "calcom":
        from services.mcp.provider_adapters.calcom import get_token as _calcom_token
        return _calcom_token(session, company_id)
    if provider == "calendly":
        from services.mcp.provider_adapters.calendly import get_token as _calendly_token
        return _calendly_token(session, company_id)
    if provider == "rocketreach_mcp":
        from services.mcp.provider_adapters.rocketreach_mcp import get_token as _rr_token
        return _rr_token(session, company_id)
    return None


# Some providers expose slightly different argument names than the LLM-friendly
# ones we advertise in tool schemas. Keep translation minimal and best-effort:
# map known aliases onto the provider's canonical key, while passing the original
# key through too so nothing is lost if a provider accepts it.
_SCHEDULING_ARG_ALIASES: dict[str, dict[str, str]] = {
    "calcom": {
        "start_time": "start",
        "event_type_id": "eventTypeId",
        "invitee_email": "attendee",
    },
}


async def _zoho_rest_fallback(capability: str, arguments: dict, company_id: int) -> dict:
    """Route Zoho capabilities to the REST executors when no Zoho MCP server row
    exists (the normal case — zoho_oauth stores credentials, not an MCP row)."""
    try:
        from mcp_tools.executors.zoho import (
            zoho_create_contact,
            zoho_query_records,
            zoho_update_contact,
        )
    except Exception as exc:
        return {"error": f"Zoho REST executor unavailable: {exc}", "provider": "zoho"}

    if capability == "create_crm_contact":
        return await zoho_create_contact(
            company_id=company_id,
            name=arguments.get("name", ""),
            email=arguments.get("email", ""),
            phone=arguments.get("phone", ""),
            company=arguments.get("company", ""),
            title=arguments.get("title", ""),
            description=arguments.get("description", ""),
        )
    if capability == "update_crm_contact":
        data = arguments.get("data") or {}
        return await zoho_update_contact(
            company_id=company_id,
            contact_id=arguments.get("record_id", ""),
            phone=data.get("phone", ""),
            email=data.get("email", ""),
            title=data.get("title", ""),
            extra_fields={k: v for k, v in data.items() if k not in ("phone", "email", "title")},
        )
    if capability == "crm_query":
        return await zoho_query_records(
            company_id=company_id,
            module=arguments.get("module", "Contacts"),
            query=arguments.get("query", ""),
        )
    return {"error": f"No Zoho REST handler for capability '{capability}'", "provider": "zoho"}


def _adapt_arguments(provider: str, arguments: dict) -> dict:
    aliases = _SCHEDULING_ARG_ALIASES.get(provider)
    if not aliases:
        return arguments
    adapted = dict(arguments)
    for src, dst in aliases.items():
        if src in adapted and dst not in adapted:
            adapted[dst] = adapted[src]
    return adapted


async def route_capability(
    session: Session,
    company_id: int,
    capability: str,
    arguments: dict,
    user_id: int,
) -> dict:
    """Route a business capability call to the best available MCP server/tool.

    Providers are tried in the order listed in CAPABILITY_MAP; the first one that
    returns a non-error result wins, so e.g. Cal.com falling over falls back to
    Calendly automatically.
    """
    tool_refs = CAPABILITY_MAP.get(capability)
    if not tool_refs:
        return {"error": f"Unknown capability '{capability}'", "available": get_capabilities()}

    last_error: dict | None = None
    for ref in tool_refs:
        if "." not in ref:
            continue
        provider, tool_name = ref.split(".", 1)

        if provider == "inventory":
            logger.info("[capability_router] inventory.%s called — args=%s company=%s", tool_name, arguments, company_id)
            from services.inventory.factory import build_inventory_service
            inv = await build_inventory_service(session, company_id)
            if tool_name == "lookup":
                result = await inv.lookup(
                    sku=arguments.get("sku", ""),
                    location=arguments.get("location"),
                )
                logger.info("[capability_router] inventory.lookup result=%s", result)
                if result:
                    return result
                last_error = {"error": "Product not found", "sku": arguments.get("sku")}
                continue
            if tool_name == "reserve":
                ok = await inv.reserve(
                    sku=arguments.get("sku", ""),
                    qty=int(arguments.get("qty", 1)),
                )
                return {"reserved": ok, "sku": arguments.get("sku")}
            continue

        server = _find_server(session, company_id, provider, tool_name)
        if not server:
            # Providers connected via OAuth without an MCPServer row still have
            # working REST backends — route to them instead of giving up.
            if provider == "apollo":
                from services.platform.mcp_client import call_external_tool
                result = await call_external_tool(
                    prefix="apollo",
                    tool_name=tool_name,
                    arguments=arguments,
                    company_id=company_id,
                )
                if result.get("error"):
                    last_error = result
                    continue
                return result
            if provider == "zoho":
                result = await _zoho_rest_fallback(capability, arguments, company_id)
                if result.get("error"):
                    last_error = result
                    continue
                return result
            logger.debug(
                "[capability_router] No server for %s/%s (company=%s)", provider, tool_name, company_id
            )
            continue

        from services.mcp.connection_service import call_server_tool
        token = _resolve_token(session, company_id, provider)
        adapted_args = _adapt_arguments(provider, arguments)
        result = await call_server_tool(server, tool_name, adapted_args, token)
        if result.get("error"):
            last_error = result
            logger.warning(
                "[capability_router] %s via %s.%s failed: %s — trying next provider",
                capability, provider, tool_name, result["error"],
            )
            continue
        return result

    if last_error is not None:
        last_error["tried"] = tool_refs
        return last_error
    return {
        "error": f"No enabled server found for capability '{capability}'",
        "tried": tool_refs,
    }
