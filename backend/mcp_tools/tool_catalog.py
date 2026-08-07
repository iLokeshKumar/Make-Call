"""
TOOL_CATALOG maps integration names to the tool names they unlock.
Tool names must match function names returned by tool_adapter.get_mistral_tools().

A company's enabled tool set = always-on groups + integrations declared via the
ENABLED_INTEGRATIONS CompanySetting key (comma-separated, e.g.
"zoho_crm,apollo_io,google_calendar") + integrations that are *actually connected*
in the DB (enabled MCP server rows, inventory sources).

Deriving enabled integrations from real connections is what makes connected apps
(Cal.com, Calendly, Apollo, RocketReach, Zoho) show up as callable tools during
voice calls and agent flows — no manual ENABLED_INTEGRATIONS setup required.
"""
from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

TOOL_CATALOG: dict[str, list[str]] = {
    # Always-on — basic voice call tools
    "core": [
        "check_icp_qualification",
        "get_product_info",
        "check_guardrails",
        "get_or_create_lead",
        "get_call_latency_summary",
    ],
    # Always-on — human handoff
    "warm_transfer": ["warm_transfer"],
    # Requires Google Calendar OAuth
    "google_calendar": [
        "book_meeting",
        "book_demo",
        "get_google_auth_url",
        "submit_google_auth_code",
        "calendar_book",
    ],
    # Requires outbound communication credentials
    "communication": ["send_communication"],
    # Requires Zoho CRM OAuth
    "zoho_crm": [
        "search_prospects",
        "create_crm_contact",
        "update_crm_contact",
        "crm_query",
    ],
    # Requires Apollo.io OAuth
    "apollo_io": [
        "search_prospects",
        "enrich_prospect",
        "enroll_sequence",
        "outreach_analytics",
    ],
    # Requires RocketReach MCP connection (fallback for search/enrichment)
    "rocketreach": [
        "search_prospects",
        "enrich_prospect",
    ],
    # Requires a connected inventory source
    "inventory": [
        "sync_product_catalog",
        "inventory_lookup",
        "inventory_reserve",
    ],
    # Requires Cal.com or Calendly connection
    "scheduling": [
        "schedule_meeting",
        "get_availability",
        "list_bookings",
        "reschedule_meeting",
        "cancel_meeting",
    ],
    # Post-call workflow — always on for companies with voice
    "post_call": [
        "get_lead_requirements",
        "upsert_lead_requirements",
        "send_csat",
        "create_ticket",
        "list_tickets",
        "set_next_action",
    ],
    # ML enrichment — always on (falls back to heuristic when insufficient data)
    "enrichment": [
        "score_lead",
        "recommend_channel",
        "check_opt_out",
    ],
    # Contact management
    "contacts": [
        "create_contact",
        "list_contacts",
    ],
}

# Integrations that are always enabled regardless of company settings / connections.
# "inventory" is always on because the built-in DB product catalog (DbProductProvider)
# is available to every company — extra InventorySource rows only layer on top.
_ALWAYS_ON = {
    "core",
    "warm_transfer",
    "post_call",
    "enrichment",
    "contacts",
    "communication",
    "google_calendar",
    "inventory",
}

# MCP server provider → integration group whose tools it unlocks.
# This mirrors services/mcp/capability_router.CAPABILITY_MAP providers.
_PROVIDER_TO_INTEGRATION: dict[str, str] = {
    "apollo": "apollo_io",
    "rocketreach_mcp": "rocketreach",
    "zoho": "zoho_crm",
    "calcom": "scheduling",
    "calendly": "scheduling",
}

# Short-TTL in-memory cache of DB-derived connections (avoids a DB hit on the
# hot tool-enablement path). Invalidated by connector routes via
# invalidate_connections_cache() whenever a connection changes.
_connections_cache: dict[int, tuple[float, set[str]]] = {}
_CONNECTIONS_TTL_SECONDS = 60


def _connected_integrations(company_id: int) -> set[str]:
    """Return integration groups that are actually connected for this company."""
    now = time.monotonic()
    entry = _connections_cache.get(company_id)
    if entry and (now - entry[0]) < _CONNECTIONS_TTL_SECONDS:
        return entry[1]

    enabled: set[str] = set()
    try:
        from database import engine, rls_company_id
        from models.mcp_server import MCPServer
        from sqlmodel import Session, select

        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                servers = session.exec(
                    select(MCPServer).where(
                        MCPServer.company_id == company_id,
                        MCPServer.enabled == True,  # noqa: E712
                    )
                ).all()
                for server in servers:
                    integration = _PROVIDER_TO_INTEGRATION.get(server.provider)
                    if integration:
                        enabled.add(integration)

                # Apollo/RocketReach connect via OAuth token (CompanySetting), and
                # Zoho via ProviderCredential — with no MCPServer row. Detect those
                # tokens directly so the tools unlock even without an MCP server row.
                from models.models import CompanySetting, ProviderCredential
                apollo_token = session.exec(
                    select(CompanySetting.id).where(
                        CompanySetting.company_id == company_id,
                        CompanySetting.key == "APOLLO_ACCESS_TOKEN",
                        CompanySetting.value != "",
                    ).limit(1)
                ).first()
                if apollo_token:
                    enabled.add("apollo_io")

                zoho_token = session.exec(
                    select(ProviderCredential.id).where(
                        ProviderCredential.company_id == company_id,
                        ProviderCredential.provider == "zoho",
                        ProviderCredential.key_name == "access_token",
                        ProviderCredential.is_active == True,  # noqa: E712
                    ).limit(1)
                ).first()
                if zoho_token:
                    enabled.add("zoho_crm")
        finally:
            rls_company_id.reset(token)
    except Exception as exc:
        logger.debug(
            "[tool_catalog] connection detection failed for company %s: %s",
            company_id,
            exc,
        )

    _connections_cache[company_id] = (now, enabled)
    return enabled


def invalidate_connections_cache(company_id: int) -> None:
    """Drop the cached connection-derived integrations for a company.

    Call this after a connector is connected/disconnected/disabled so the next
    tool-resolution sees the new state immediately.
    """
    _connections_cache.pop(company_id, None)


def integrations_for_company(company_id: int) -> list[str]:
    """Return the list of integration names enabled for this company."""
    from utils import settings_cache as _sc
    raw = _sc.get("ENABLED_INTEGRATIONS", user_id=company_id) or ""
    configured = {s.strip() for s in raw.split(",") if s.strip()}
    return list(_ALWAYS_ON | configured | _connected_integrations(company_id))


def tool_names_for_company(company_id: int) -> set[str]:
    """Return the flat set of tool function names available to this company."""
    names: set[str] = set()
    for integration in integrations_for_company(company_id):
        names.update(TOOL_CATALOG.get(integration, []))
    return names
