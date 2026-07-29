"""
TOOL_CATALOG maps integration names to the tool names they unlock.
Tool names must match function names returned by tool_adapter.get_mistral_tools().

Companies declare enabled integrations via the ENABLED_INTEGRATIONS CompanySetting key
(comma-separated, e.g. "zoho_crm,apollo_io,google_calendar").
The "core" and "warm_transfer" groups are always included.
"""
from __future__ import annotations

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
    # Requires a connected inventory source
    "inventory": [
        "sync_product_catalog",
        "inventory_lookup",
        "inventory_reserve",
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

# Integrations that are always enabled regardless of company settings
_ALWAYS_ON = {"core", "warm_transfer", "post_call", "enrichment", "contacts"}


def integrations_for_company(company_id: int) -> list[str]:
    """Return the list of integration names enabled for this company."""
    from utils import settings_cache as _sc
    raw = _sc.get("ENABLED_INTEGRATIONS", user_id=company_id) or ""
    configured = {s.strip() for s in raw.split(",") if s.strip()}
    return list(_ALWAYS_ON | configured)


def tool_names_for_company(company_id: int) -> set[str]:
    """Return the flat set of tool function names available to this company."""
    names: set[str] = set()
    for integration in integrations_for_company(company_id):
        names.update(TOOL_CATALOG.get(integration, []))
    return names
