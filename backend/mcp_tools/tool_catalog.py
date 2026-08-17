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
    # Requires Google Calendar OAuth. Besides native booking (book_meeting/
    # book_demo with Google Meet links), Google Calendar is the auto-fallback
    # provider for the scheduling capabilities when Cal.com/Calendly/Microsoft
    # are NOT connected — it can create events, check availability, list,
    # reschedule and cancel on the company's Google Calendar.
    "google_calendar": [
        "schedule_demo",
        "book_meeting",
        "book_demo",
        "get_google_auth_url",
        "submit_google_auth_code",
        "schedule_meeting",
        "get_availability",
        "list_bookings",
        "reschedule_meeting",
        "cancel_meeting",
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
    # Requires HubSpot OAuth (REST capability fallback for CRM + prospect search)
    "hubspot_crm": [
        "search_prospects",
        "enrich_prospect",
        "create_crm_contact",
        "update_crm_contact",
        "crm_query",
    ],
    # Requires Microsoft 365 OAuth (Graph calendar + email)
    "microsoft_365": [
        "schedule_demo",
        "schedule_meeting",
        "get_availability",
        "list_bookings",
        "cancel_meeting",
        "send_microsoft_email",
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
    # Requires Zoom OAuth connection (Meetings MCP server, read-only tools)
    "zoom": [
        "search_meetings",
        "get_meeting_assets",
        "list_meeting_recordings",
        "get_recording_resource",
    ],
    # Requires the Zoom app to have granted the meeting:write scope (REST meeting
    # creation via POST /v2/users/me/meetings). Deliberately separate from "zoom"
    # so agents only see create_meeting once the stored Zoom scopes prove the
    # scope is granted (see _connected_integrations) — not merely connected.
    "zoom_write": [
        "create_meeting",
    ],
    # Requires Cal.com or Calendly connection
    "scheduling": [
        "schedule_demo",
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
# NOTE: google_calendar and communication are deliberately NOT always-on — their
# tools (book_meeting/book_demo, send_communication) only load when the company has
# actually connected Google Calendar / outbound communication credentials (see
# _connected_integrations). This keeps the per-call LLM tool payload lean.
_ALWAYS_ON = {
    "core",
    "warm_transfer",
    "post_call",
    "enrichment",
    "contacts",
    "inventory",
}

# Core conversation tools that stay available to EVERY agent even when a
# per-agent allowlist (VoiceAgentTool rows) is configured. Gating is intended to
# trim the heavy domain tools (scheduling, Zoom, CRM, enrichment, inventory,
# booking) to cut LLM payload size — never to silently strip an agent of the
# tools needed to run any conversation.
CORE_TOOL_NAMES: set[str] = set(TOOL_CATALOG["core"]) | set(TOOL_CATALOG["warm_transfer"])

# MCP server provider → integration group whose tools it unlocks.
# This mirrors services/mcp/capability_router.CAPABILITY_MAP providers.
_PROVIDER_TO_INTEGRATION: dict[str, str] = {
    "apollo": "apollo_io",
    "rocketreach_mcp": "rocketreach",
    "zoho": "zoho_crm",
    "calcom": "scheduling",
    "calendly": "scheduling",
    "zoom": "zoom",
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

                # Zoom meeting creation (create_meeting) is gated on the
                # meeting:write scope: only unlock the zoom_write group when the
                # stored Zoom scopes prove it, or when the scope state is unknown
                # (legacy connection — fail open so a valid token is never hidden;
                # the runtime executor + Settings hint cover definitive missing).
                if "zoom" in enabled:
                    from routes.zoom_oauth import zoom_meeting_write_granted
                    if zoom_meeting_write_granted(session, company_id) is not False:
                        enabled.add("zoom_write")

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

                # HubSpot and Microsoft 365 also connect via OAuth tokens stored
                # in ProviderCredential (no MCPServer row). Detect them so their
                # capability tools unlock without an MCP server row.
                hubspot_token = session.exec(
                    select(ProviderCredential.id).where(
                        ProviderCredential.company_id == company_id,
                        ProviderCredential.provider == "hubspot",
                        ProviderCredential.key_name == "access_token",
                        ProviderCredential.is_active == True,  # noqa: E712
                    ).limit(1)
                ).first()
                if hubspot_token:
                    enabled.add("hubspot_crm")

                ms_token = session.exec(
                    select(ProviderCredential.id).where(
                        ProviderCredential.company_id == company_id,
                        ProviderCredential.provider == "microsoft",
                        ProviderCredential.key_name == "access_token",
                        ProviderCredential.is_active == True,  # noqa: E712
                    ).limit(1)
                ).first()
                if ms_token:
                    enabled.add("microsoft_365")

                # Google Calendar connects via OAuth tokens stored as company
                # settings (GCAL_* — saved by routes/calendar.py, the Google
                # auth flow in routes/auth.py, and the MCP calendar executors).
                gcal_token = session.exec(
                    select(CompanySetting.id).where(
                        CompanySetting.company_id == company_id,
                        CompanySetting.key == "GCAL_ACCESS_TOKEN",
                        CompanySetting.value != "",
                    ).limit(1)
                ).first()
                if gcal_token:
                    enabled.add("google_calendar")

                # Outbound communication (send_communication) needs SMTP for
                # email or a WhatsApp-capable telephony provider (Twilio/Exotel).
                # Presence of any of these keys unlocks the communication group.
                from models.models import User, UserSetting
                comm_key = session.exec(
                    select(CompanySetting.id).where(
                        CompanySetting.company_id == company_id,
                        CompanySetting.key.in_([
                            "SMTP_HOST",
                            "SMTP_SERVER",
                            "SMTP_PASSWORD",
                            "SMTP_FROM_EMAIL",
                            "TWILIO_ACCOUNT_SID",
                            "EXOTEL_ACCOUNT_SID",
                            "WHATSAPP_NUMBER",
                            "WHATSAPP_NUMBER_FROM",
                        ]),
                        CompanySetting.value != "",
                    ).limit(1)
                ).first()
                if comm_key:
                    enabled.add("communication")
                else:
                    # SMTP can also be configured per-user (My Email settings,
                    # saved as UserSetting rows). get_email_credential() prefers
                    # the user-level value, so a company whose members use their
                    # own SMTP is fully capable of sending email — unlock here too.
                    user_smtp = session.exec(
                        select(UserSetting.id)
                        .join(User, User.id == UserSetting.user_id)
                        .where(
                            User.company_id == company_id,
                            UserSetting.key.in_([
                                "SMTP_HOST",
                                "SMTP_SERVER",
                                "SMTP_USERNAME",
                                "SMTP_PASSWORD",
                                "SMTP_FROM_EMAIL",
                            ]),
                            UserSetting.value != "",
                        ).limit(1)
                    ).first()
                    if user_smtp:
                        enabled.add("communication")
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
    tool-resolution sees the new state immediately. Also drops the dependent
    connected-providers detection cache (services/mcp/connected_providers) so
    the per-call prompt block and Settings card settle right away too.
    """
    _connections_cache.pop(company_id, None)
    try:
        from services.mcp.connected_providers import invalidate_providers_cache
        invalidate_providers_cache(company_id)
    except Exception:
        # The providers cache is best-effort — never block tool resolution on it.
        pass


# Per-agent allowlist (VoiceAgentTool rows) cache: keyed by (company_id, agent_id),
# short TTL like the connections cache. Invalidated by the voice-agent tool routes
# whenever an agent's tool rows change.
_agent_tools_cache: dict[tuple[int, int], tuple[float, set[str]]] = {}
_AGENT_TOOLS_TTL_SECONDS = 30


def agent_tool_names(company_id: int, agent_id: int) -> set[str]:
    """Return the active per-agent tool allowlist from VoiceAgentTool rows.

    Includes both agent-specific rows (agent_id == agent_id) and company-wide
    rows (agent_id IS NULL). Returns an EMPTY set when the agent has no active
    rows — callers treat that as "no restriction" (fall back to the company's
    full enabled tool set).
    """
    key = (company_id, agent_id)
    now = time.monotonic()
    entry = _agent_tools_cache.get(key)
    if entry and (now - entry[0]) < _AGENT_TOOLS_TTL_SECONDS:
        return entry[1]

    names: set[str] = set()
    try:
        from database import engine, rls_company_id
        from models.models import VoiceAgentTool
        from sqlmodel import Session, select

        token = rls_company_id.set(company_id)
        try:
            with Session(engine) as session:
                rows = session.exec(
                    select(VoiceAgentTool).where(
                        VoiceAgentTool.company_id == company_id,
                        VoiceAgentTool.is_active == True,  # noqa: E712
                        (VoiceAgentTool.agent_id == agent_id)
                        | (VoiceAgentTool.agent_id.is_(None)),
                    )
                ).all()
                names = {row.name for row in rows if row.name}
        finally:
            rls_company_id.reset(token)
        _agent_tools_cache[key] = (now, names)
    except Exception as exc:
        # Do NOT cache on error — a transient DB failure must not pin an empty
        # allowlist (fail-open) for the TTL; the next call retries.
        logger.debug(
            "[tool_catalog] agent tool lookup failed for company %s agent %s: %s",
            company_id,
            agent_id,
            exc,
        )
    return names


def invalidate_agent_tools_cache(company_id: int) -> None:
    """Drop cached per-agent tool allowlists for a company.

    Call this after a voice agent's tools change (create/delete/update) so the
    next tool-resolution sees the new allowlist immediately.
    """
    for key in [k for k in _agent_tools_cache if k[0] == company_id]:
        _agent_tools_cache.pop(key, None)


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
