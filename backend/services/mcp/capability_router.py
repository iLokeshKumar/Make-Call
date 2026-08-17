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

PROVIDER_PRIORITY: dict[str, int] = {
    # Lower number = tried first (higher priority) for capabilities where the
    # provider is a candidate. This is the source of truth documented in the
    # LLM-facing tool schemas (tool_adapter._CAPABILITY_TOOLS).
    "apollo": 10,
    "zoho": 20,
    "hubspot": 30,
    "calcom": 40,
    "calendly": 50,
    "microsoft": 60,
    "google_calendar": 65,
    "rocketreach_mcp": 70,
    "zoom": 80,
    "inventory": 90,
}

# "provider.tool_name" entries are tried in order; first match that has an
# enabled MCPServer (or a working REST fallback) for this company wins.
#
# PROVIDER PRIORITY ORDER (default, when the LLM does not name a provider):
#   * Prospect search      Apollo → HubSpot contacts → RocketReach
#   * Contact enrichment   Apollo → HubSpot (via CRM record lookup) → RocketReach
#   * CRM writes/queries   Zoho → HubSpot
#   * Scheduling           Cal.com → Calendly → Microsoft 365 → Google Calendar
#                          (Google Calendar is the auto-fallback when no external
#                          scheduler is connected; it books a Google Calendar
#                          event with a Google Meet link)
#   * Meeting creation     Zoom (REST) — meeting:write scope required
#   * Meeting intelligence Zoom Meetings MCP (read-only)
#
# The LLM can also pass a `provider` argument (e.g. "hubspot") to a capability
# to force that provider first; the list below then acts as the fallback chain.
CAPABILITY_MAP: dict[str, list[str]] = {
    "search_prospects":     [
        "apollo.mixed_people_api_search",
        "apollo.contacts_search",
        "hubspot.crm_contacts_search",
        "rocketreach_mcp.person_search",
    ],
    "enrich_prospect":      [
        "apollo.people_match",
        "apollo.organizations_enrich",
        "hubspot.crm_contacts_search",
        "rocketreach_mcp.person_lookup",
    ],
    "create_crm_contact":   ["zoho.createRecords", "hubspot.crm_contacts_create"],
    "update_crm_contact":   ["zoho.updateRecords", "hubspot.crm_contacts_update"],
    "crm_query":            ["zoho.executeCOQLQuery", "zoho.searchRecords", "hubspot.crm_objects_search"],
    "enroll_sequence":      ["apollo.emailer_campaigns_add_contact_ids"],
    "outreach_analytics":   ["apollo.analytics_sync_report"],
    "inventory_lookup":     ["inventory.lookup"],
    "inventory_reserve":    ["inventory.reserve"],
    # Scheduling via Cal.com / Calendly / Microsoft 365 / Google Calendar
    # (Google Calendar is the auto-fallback when no external scheduler is
    # connected — it creates a calendar event with a Google Meet link.)
    "schedule_meeting":     ["calcom.create_booking", "calendly.create_event", "microsoft.graph_create_event", "google_calendar.create_event"],
    "reschedule_meeting":   ["calcom.reschedule_booking", "calendly.reschedule_event", "microsoft.graph_update_event", "google_calendar.reschedule_event"],
    "get_availability":     ["calcom.get_availability", "calendly.get_availability", "microsoft.graph_get_schedule", "google_calendar.get_availability"],
    "list_bookings":        ["calcom.get_bookings", "calendly.list_scheduled_events", "microsoft.graph_list_events", "google_calendar.list_events"],
    "cancel_meeting":       ["calcom.cancel_booking", "calendly.cancel_event", "microsoft.graph_cancel_event", "google_calendar.cancel_event"],
    # Email via Microsoft 365 (Graph sendMail)
    "send_microsoft_email": ["microsoft.graph_send_mail"],
    # Meeting creation via Zoom REST (auto-fallback link provider for bookings)
    "create_meeting":       ["zoom.create_meeting"],
    # Meeting intelligence via Zoom Meetings MCP
    "search_meetings":       ["zoom.search_meetings"],
    "get_meeting_assets":    ["zoom.get_meeting_assets"],
    "list_meeting_recordings": ["zoom.recordings_list"],
    "get_recording_resource":  ["zoom.get_recording_resource"],
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
    if provider == "zoom":
        from services.mcp.provider_adapters.zoom import get_token as _zoom_token
        return _zoom_token(session, company_id)
    if provider == "hubspot":
        from services.mcp.provider_adapters.hubspot import get_token as _hubspot_token
        return _hubspot_token(session, company_id)
    if provider == "microsoft":
        from services.mcp.provider_adapters.microsoft import get_token as _ms_token
        return _ms_token(session, company_id)
    if provider == "google_calendar":
        # Google Calendar stores tokens as company settings (GCAL_*) rather than
        # ProviderCredential — return a truthy marker; the REST fallback reads
        # the real credentials itself.
        return _gcal_connected(session, company_id)
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


async def _hubspot_rest_fallback(capability: str, arguments: dict, company_id: int) -> dict:
    """Route HubSpot capabilities to the REST executors when no HubSpot MCP
    server row exists (the normal case — hubspot_oauth stores credentials, not
    an MCP row)."""
    try:
        from mcp_tools.executors.hubspot import (
            hubspot_create_contact,
            hubspot_query_records,
            hubspot_search_contacts,
            hubspot_update_contact,
        )
    except Exception as exc:
        return {"error": f"HubSpot REST executor unavailable: {exc}", "provider": "hubspot"}

    if capability == "search_prospects":
        return await hubspot_search_contacts(
            company_id=company_id,
            query=arguments.get("query", ""),
            person_title=arguments.get("person_title", ""),
            company=arguments.get("company", ""),
            location=arguments.get("location", ""),
            limit=arguments.get("limit", 10),
        )
    if capability == "enrich_prospect":
        return await hubspot_search_contacts(
            company_id=company_id,
            query=arguments.get("email", "") or arguments.get("name", ""),
            limit=1,
        )
    if capability == "create_crm_contact":
        return await hubspot_create_contact(
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
        # Normalize the LLM-friendly 'title' key onto HubSpot's 'jobtitle'
        # property; remaining keys pass through as HubSpot property names.
        props = dict(data)
        if props.get("title"):
            props["jobtitle"] = props.pop("title")
        return await hubspot_update_contact(
            company_id=company_id,
            contact_id=arguments.get("record_id", ""),
            data=props,
        )
    if capability == "crm_query":
        return await hubspot_query_records(
            company_id=company_id,
            object_type=(arguments.get("module") or arguments.get("object_type") or "contacts").lower(),
            query=arguments.get("query", ""),
            limit=arguments.get("limit", 25),
        )
    return {"error": f"No HubSpot REST handler for capability '{capability}'", "provider": "hubspot"}


async def _microsoft_rest_fallback(capability: str, arguments: dict, company_id: int) -> dict:
    """Route Microsoft capabilities to the Graph REST executors when no Microsoft
    MCP server row exists (the normal case — microsoft_oauth stores credentials,
    not an MCP row)."""
    try:
        from mcp_tools.executors.microsoft import (
            ms_cancel_event,
            ms_create_event,
            ms_get_availability,
            ms_list_events,
            ms_send_email,
            ms_update_event,
        )
    except Exception as exc:
        return {"error": f"Microsoft REST executor unavailable: {exc}", "provider": "microsoft"}

    if capability == "get_availability":
        return await ms_get_availability(
            company_id=company_id,
            date=arguments.get("date", ""),
            start_time=arguments.get("start_time", ""),
            end_time=arguments.get("end_time", ""),
        )
    if capability == "list_bookings":
        return await ms_list_events(
            company_id=company_id,
            from_date=arguments.get("from_date", ""),
            to_date=arguments.get("to_date", ""),
            status=arguments.get("status", ""),
            limit=arguments.get("limit", 25),
        )
    if capability == "schedule_meeting":
        end_time = arguments.get("end_time", "")
        return await ms_create_event(
            company_id=company_id,
            subject=arguments.get("subject", "Meeting"),
            start_time=arguments.get("start_time", ""),
            end_time=end_time,
            invitee_email=arguments.get("invitee_email", ""),
            invitee_name=arguments.get("invitee_name", ""),
            notes=arguments.get("notes", ""),
        )
    if capability == "cancel_meeting":
        return await ms_cancel_event(
            company_id=company_id,
            event_id=arguments.get("booking_id", ""),
            reason=arguments.get("reason", ""),
        )
    if capability == "reschedule_meeting":
        return await ms_update_event(
            company_id=company_id,
            event_id=arguments.get("booking_id", ""),
            start_time=arguments.get("new_start_time", ""),
            end_time=arguments.get("end_time", ""),
            subject=arguments.get("subject", ""),
        )
    if capability == "send_microsoft_email":
        return await ms_send_email(
            company_id=company_id,
            to_email=arguments.get("to_email", ""),
            subject=arguments.get("subject", ""),
            body=arguments.get("body", ""),
            cc_email=arguments.get("cc_email", ""),
        )
    return {"error": f"No Microsoft REST handler for capability '{capability}'", "provider": "microsoft"}


async def _google_calendar_rest_fallback(capability: str, arguments: dict, company_id: int) -> dict:
    """Route scheduling capabilities to the Google Calendar REST executors when
    no external scheduler (Cal.com/Calendly/Microsoft) is connected — Google
    Calendar is the auto-fallback that books events with Google Meet links."""
    try:
        from mcp_tools.executors.google_calendar import (
            gcal_cancel_event,
            gcal_create_event,
            gcal_get_availability,
            gcal_list_events,
            gcal_reschedule_event,
        )
    except Exception as exc:
        return {"error": f"Google Calendar REST executor unavailable: {exc}", "provider": "google_calendar"}

    if capability == "schedule_meeting":
        return await gcal_create_event(
            company_id=company_id,
            subject=arguments.get("subject", "") or arguments.get("invitee_name", "") or "Meeting",
            start_time=arguments.get("start_time", ""),
            end_time=arguments.get("end_time", ""),
            invitee_email=arguments.get("invitee_email", ""),
            invitee_name=arguments.get("invitee_name", ""),
            notes=arguments.get("notes", ""),
            duration_minutes=arguments.get("duration_minutes", 30),
        )
    if capability == "get_availability":
        return await gcal_get_availability(
            company_id=company_id,
            date=arguments.get("date", ""),
            start_time=arguments.get("start_time", ""),
            end_time=arguments.get("end_time", ""),
        )
    if capability == "list_bookings":
        return await gcal_list_events(
            company_id=company_id,
            from_date=arguments.get("from_date", ""),
            to_date=arguments.get("to_date", ""),
            status=arguments.get("status", ""),
            limit=arguments.get("limit", 25),
        )
    if capability == "reschedule_meeting":
        return await gcal_reschedule_event(
            company_id=company_id,
            event_id=arguments.get("booking_id", ""),
            new_start_time=arguments.get("new_start_time", ""),
            end_time=arguments.get("end_time", ""),
            subject=arguments.get("subject", ""),
        )
    if capability == "cancel_meeting":
        return await gcal_cancel_event(
            company_id=company_id,
            event_id=arguments.get("booking_id", ""),
            reason=arguments.get("reason", ""),
        )
    return {"error": f"No Google Calendar REST handler for capability '{capability}'", "provider": "google_calendar"}


# Zoom Meetings MCP tools expect slightly different keys than the LLM-friendly
# ones advertised in tool schemas. Map them best-effort (originals pass through).
_ZOOM_ARG_ALIASES: dict[str, str] = {
    "query": "search_key",
    "from_date": "from",
    "to_date": "to",
}


def _gcal_connected(session: Session, company_id: int) -> Optional[str]:
    """Return a truthy marker when Google Calendar is connected (GCAL token present)."""
    from models.models import CompanySetting
    row = session.exec(
        select(CompanySetting.id).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == "GCAL_ACCESS_TOKEN",
            CompanySetting.value != "",
        ).limit(1)
    ).first()
    return "connected" if row else None


def _adapt_arguments(provider: str, arguments: dict) -> dict:
    adapted = dict(arguments)
    if provider == "zoom":
        for src, dst in _ZOOM_ARG_ALIASES.items():
            if src in adapted and dst not in adapted:
                adapted[dst] = adapted[src]
        return adapted
    aliases = _SCHEDULING_ARG_ALIASES.get(provider)
    if not aliases:
        return adapted
    for src, dst in aliases.items():
        if src in adapted and dst not in adapted:
            adapted[dst] = adapted[src]
    return adapted


def _ordered_tool_refs(capability: str, arguments: dict) -> list[str]:
    """Return CAPABILITY_MAP refs for a capability, honoring an explicit
    ``provider`` argument.

    Priority rules:
      1. If the LLM passes ``provider`` (e.g. "hubspot"), that provider is moved
         to the front and the rest keep their documented CAPABILITY_MAP order.
      2. Otherwise the CAPABILITY_MAP order itself is the priority (see
         PROVIDER_PRIORITY for the numeric ranking).
    """
    tool_refs = CAPABILITY_MAP.get(capability) or []
    wanted = str(arguments.get("provider") or "").strip().lower()
    if not wanted:
        return list(tool_refs)
    wanted_refs = [r for r in tool_refs if r.split(".", 1)[0] == wanted]
    if not wanted_refs:
        # Unknown provider — keep the documented order (don't invent routes).
        return list(tool_refs)
    others = [r for r in tool_refs if r.split(".", 1)[0] != wanted]
    return wanted_refs + others


async def route_capability(
    session: Session,
    company_id: int,
    capability: str,
    arguments: dict,
    user_id: int,
) -> dict:
    """Route a business capability call to the best available MCP server/tool.

    Providers are tried in priority order — either the order listed in
    CAPABILITY_MAP (see PROVIDER_PRIORITY for the documented ranking) or, when
    the caller passes an explicit ``provider`` argument, that provider first
    with the map order as the fallback chain. The first provider that returns
    a non-error result wins, so e.g. Cal.com falling over falls back to
    Calendly automatically.
    """
    tool_refs = _ordered_tool_refs(capability, arguments)
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
            if provider == "hubspot":
                result = await _hubspot_rest_fallback(capability, arguments, company_id)
                if result.get("error"):
                    last_error = result
                    continue
                return result
            if provider == "microsoft":
                result = await _microsoft_rest_fallback(capability, arguments, company_id)
                if result.get("error"):
                    last_error = result
                    continue
                return result
            if provider == "google_calendar":
                result = await _google_calendar_rest_fallback(capability, arguments, company_id)
                if result.get("error"):
                    last_error = result
                    continue
                return result
            if provider == "zoom" and capability == "create_meeting":
                from mcp_tools.executors.zoom_rest import zoom_create_meeting
                result = await zoom_create_meeting(
                    company_id=company_id,
                    topic=arguments.get("topic", "") or arguments.get("subject", "") or "Meeting",
                    start_time=arguments.get("start_time", ""),
                    duration_minutes=arguments.get("duration_minutes", 30),
                    attendee_email=arguments.get("attendee_email", ""),
                    settings=arguments.get("settings"),
                )
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
