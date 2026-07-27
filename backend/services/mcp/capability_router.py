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
    "search_prospects":     ["apollo.mixed_people_api_search", "apollo.contacts_search"],
    "enrich_prospect":      ["apollo.people_match", "apollo.organizations_enrich"],
    "create_crm_contact":   ["zoho.createRecords"],
    "update_crm_contact":   ["zoho.updateRecords"],
    "crm_query":            ["zoho.executeCOQLQuery", "zoho.searchRecords"],
    "enroll_sequence":      ["apollo.emailer_campaigns_add_contact_ids"],
    "outreach_analytics":   ["apollo.analytics_sync_report"],
    "inventory_lookup":     ["inventory.lookup"],
    "inventory_reserve":    ["inventory.reserve"],
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
    return None


async def route_capability(
    session: Session,
    company_id: int,
    capability: str,
    arguments: dict,
    user_id: int,
) -> dict:
    """Route a business capability call to the best available MCP server/tool."""
    tool_refs = CAPABILITY_MAP.get(capability)
    if not tool_refs:
        return {"error": f"Unknown capability '{capability}'", "available": get_capabilities()}

    for ref in tool_refs:
        if "." not in ref:
            continue
        provider, tool_name = ref.split(".", 1)

        if provider == "inventory":
            from services.inventory.factory import build_inventory_service
            inv = await build_inventory_service(session, company_id)
            if tool_name == "lookup":
                result = await inv.lookup(
                    sku=arguments.get("sku", ""),
                    location=arguments.get("location"),
                )
                return result or {"error": "Product not found", "sku": arguments.get("sku")}
            if tool_name == "reserve":
                ok = await inv.reserve(
                    sku=arguments.get("sku", ""),
                    qty=int(arguments.get("qty", 1)),
                )
                return {"reserved": ok, "sku": arguments.get("sku")}
            continue

        server = _find_server(session, company_id, provider, tool_name)
        if not server:
            logger.debug(
                "[capability_router] No server for %s/%s (company=%s)", provider, tool_name, company_id
            )
            continue

        from services.mcp.connection_service import call_server_tool
        token = _resolve_token(session, company_id, provider)
        return await call_server_tool(server, tool_name, arguments, token)

    return {
        "error": f"No enabled server found for capability '{capability}'",
        "tried": tool_refs,
    }
