"""
connected_providers.py - Per-company "what is connected" context for agents + Settings.

One detection pass (reusing mcp_tools.tool_catalog.integrations_for_company —
the same cached source that gates the per-call LLM tool payload) feeds two
builders:

  * connected_providers_context(company_id) -> str
      Plain-text block injected into every call's system prompt so the agent
      knows which providers are LIVE for THIS company and the priority order
      between overlapping ones (scheduling, meeting links, prospects, CRM).
      The agent never guesses a provider and never calls a disconnected app.

  * build_capabilities_summary(company_id) -> dict
      JSON payload for the Settings "Effective capabilities" card — the same
      truth as the prompt injection, so what an admin sees in Settings and what
      the agent knows on a call can never diverge.

Provider ids match services/mcp/capability_router (PROVIDER_PRIORITY /
CAPABILITY_MAP); the capability chains below mirror its documented order.
"""
from __future__ import annotations

import logging
import time

from sqlmodel import Session, select

logger = logging.getLogger(__name__)

# Provider id (as used in capability_router) -> human display label.
PROVIDER_LABELS: dict[str, str] = {
    "apollo": "Apollo.io",
    "zoho": "Zoho CRM",
    "hubspot": "HubSpot",
    "calcom": "Cal.com",
    "calendly": "Calendly",
    "microsoft": "Microsoft 365",
    "google_calendar": "Google Calendar",
    "rocketreach_mcp": "RocketReach",
    "zoom": "Zoom",
    "inventory": "Inventory",
    "communication": "Email / WhatsApp",
}

# provider -> integration group that proves it is connected. Mirrors the
# _PROVIDER_TO_INTEGRATION map in mcp_tools/tool_catalog.
_PROVIDER_GROUP: dict[str, str] = {
    "apollo": "apollo_io",
    "zoho": "zoho_crm",
    "hubspot": "hubspot_crm",
    "calcom": "scheduling",
    "calendly": "scheduling",
    "microsoft": "microsoft_365",
    "google_calendar": "google_calendar",
    "rocketreach_mcp": "rocketreach",
    "zoom": "zoom",
    "inventory": "inventory",
    "communication": "communication",
}

# Short-TTL in-memory cache of _detect() results (the settings card polls every
# ~20s and the prompt injects on every call, so the detection must not hit the
# DB repeatedly). Invalidated via invalidate_providers_cache(), which is wired
# into mcp_tools.tool_catalog.invalidate_connections_cache — the single choke
# point every connector route already calls on connect/disconnect.
_providers_cache: dict[int, tuple[float, dict]] = {}
_PROVIDERS_TTL_SECONDS = 30


def invalidate_providers_cache(company_id: int) -> None:
    """Drop the cached detection for a company (call after a connection change)."""
    _providers_cache.pop(company_id, None)


# Provider ids available to EVERY company without any external connection (the
# built-in DB product catalog). These don't count as "connected integrations"
# for the no-tools branch of the prompt: a bare account gets the short honesty
# guard instead of ~200 tokens of generic tool guidance it can't use. The
# Settings card still lists inventory (it IS a real capability).
_BUILTIN_PROVIDERS: frozenset[str] = frozenset({"inventory"})


# Capability rows shared by the prompt injection AND the Settings card.
# Providers are listed in the documented priority order (source of truth:
# services/mcp/capability_router.PROVIDER_PRIORITY / CAPABILITY_MAP).
#   google_fallback=True → Google Calendar is the auto-fallback provider here.
#   zoom_write_gated=True → the row is gated on the Zoom meeting:write scope.
#   suggest → provider ids the Settings card offers as one-click unlock paths
#             when the row is unavailable (in priority order).
_CAPABILITY_ROWS: list[dict] = [
    {
        "key": "scheduling",
        "label": "Scheduling",
        "providers": ["calcom", "calendly", "microsoft", "google_calendar"],
        "google_fallback": True,
        "suggest": ["calcom", "calendly", "google_calendar"],
    },
    {
        "key": "meeting_links",
        "label": "Meeting links",
        "providers": ["google_calendar", "zoom"],
        "zoom_write_gated": True,
        "suggest": ["zoom", "google_calendar"],
    },
    {
        "key": "prospect_search",
        "label": "Prospect search",
        "providers": ["apollo", "hubspot", "rocketreach_mcp"],
        "suggest": ["apollo", "rocketreach_mcp"],
    },
    {
        "key": "contact_enrichment",
        "label": "Contact enrichment",
        "providers": ["apollo", "hubspot", "rocketreach_mcp"],
        "suggest": ["apollo", "rocketreach_mcp"],
    },
    {
        "key": "crm",
        "label": "CRM",
        "providers": ["zoho", "hubspot"],
        "suggest": ["zoho", "hubspot"],
    },
    {
        "key": "meeting_intelligence",
        "label": "Meeting intelligence",
        "providers": ["zoom"],
        "suggest": ["zoom"],
    },
    {
        "key": "email",
        "label": "Email",
        "providers": ["microsoft"],
        "suggest": ["microsoft"],
    },
    {
        "key": "messaging",
        "label": "Outbound messaging",
        "providers": ["communication"],
        "suggest": ["communication"],
    },
    {
        "key": "inventory",
        "label": "Product catalog & inventory",
        "providers": ["inventory"],
        "suggest": [],
    },
]


def _detect(company_id: int) -> dict:
    """Return per-company provider connectivity facts (cached 30s).

    The heavy lifting (enabled MCP servers, OAuth tokens, Zoom scopes) already
    lives in mcp_tools.tool_catalog._connected_integrations (itself cached) —
    this reuses its public `integrations_for_company` output and only adds the
    one thing it can't express: splitting the collapsed 'scheduling' group into
    Cal.com vs Calendly.

    The Zoom meeting:write tri-state is derived from the integration groups the
    same way tool_catalog gates the create_meeting tool:
      * 'zoom_write' in groups  → granted-or-unknown (fail-open) → True
      * 'zoom' in groups, no 'zoom_write' → definitively missing → False
      * zoom not connected → None
    NOTE: unknown/legacy connections report True (fail-open — the tool is visible
    for them), so True does not strictly mean "scopes recorded as granted"; it
    means "meeting creation is available to agents". No extra DB query, and it
    always matches what the tool gate shows the agent.
    """
    now = time.monotonic()
    entry = _providers_cache.get(company_id)
    if entry and (now - entry[0]) < _PROVIDERS_TTL_SECONDS:
        return entry[1]

    from mcp_tools.tool_catalog import integrations_for_company

    groups = set(integrations_for_company(company_id))
    connected: set[str] = {p for p, g in _PROVIDER_GROUP.items() if g in groups}
    unknown_scheduling = False

    if "scheduling" in groups:
        # The scheduling group collapses Cal.com + Calendly into one flag; name
        # them precisely from the enabled MCP server rows (single small query,
        # cached by this function's own 30s TTL).
        server_providers: set[str] = set()
        try:
            from database import engine, rls_company_id
            from models.mcp_server import MCPServer

            token = rls_company_id.set(company_id)
            try:
                with Session(engine) as session:
                    rows = session.exec(
                        select(MCPServer.provider).where(
                            MCPServer.company_id == company_id,
                            MCPServer.enabled == True,  # noqa: E712
                        )
                    ).all()
                    server_providers = {r for (r,) in rows}
            finally:
                rls_company_id.reset(token)
        except Exception as exc:
            logger.debug("[connected_providers] server-row lookup failed: %s", exc)

        if "calcom" in server_providers:
            connected.add("calcom")
        if "calendly" in server_providers:
            connected.add("calendly")
        if "calcom" not in connected and "calendly" not in connected:
            unknown_scheduling = True

    if "zoom" in groups:
        zoom_write_granted = "zoom_write" in groups
    else:
        zoom_write_granted = None

    info = {
        "groups": groups,
        "connected": connected,
        "unknown_scheduling": unknown_scheduling,
        "zoom_write_granted": zoom_write_granted,
    }
    _providers_cache[company_id] = (now, info)
    return info


def _row_analysis(row: dict, info: dict) -> dict:
    """Analyse one capability row: per-provider state + row-level status."""
    connected = info["connected"]
    providers: list[dict] = []
    has_connected = False
    degraded = False

    for provider in row["providers"]:
        label = PROVIDER_LABELS.get(provider, provider)
        state = "disconnected"
        note = None

        if provider == "zoom" and row.get("zoom_write_gated"):
            if provider in connected:
                if info["zoom_write_granted"] is False:
                    state = "degraded"
                    degraded = True
                    note = "meeting:write scope missing — meeting creation hidden; reconnect to grant"
                else:
                    state = "connected"
                    has_connected = True
                    note = "REST meeting creation (meeting:write granted)"
            providers.append({"provider": provider, "label": label, "state": state, "note": note})
            continue

        if provider in connected:
            state = "connected"
            has_connected = True
            if provider == "google_calendar":
                note = "Google Meet link fallback" if row.get("google_fallback") else "Provides Google Meet links"
            elif provider == "communication":
                note = "SMTP / WhatsApp configured"
        elif info["unknown_scheduling"] and provider == "calcom":
            state = "connected"
            has_connected = True
            note = "Cal.com or Calendly connected"

        providers.append({"provider": provider, "label": label, "state": state, "note": note})

    status = "available" if has_connected else ("degraded" if degraded else "unavailable")
    # When nothing works, offer the documented unlock paths so the Settings card
    # can suggest connectors to connect (no suggestions for available/degraded).
    suggest: list[str] = list(row.get("suggest", [])) if status == "unavailable" else []
    return {
        "key": row["key"],
        "label": row["label"],
        "status": status,
        "chain": " → ".join(PROVIDER_LABELS.get(p, p) for p in row["providers"]),
        "providers": providers,
        "suggest": suggest,
    }


# Header/closing for the tailored '### CONNECTED TOOLS' guidance block.
_TOOL_GUIDANCE_HEADER = (
    "### CONNECTED TOOLS\n"
    "Use the company's connected tools proactively and positively whenever "
    "they genuinely help the customer:"
)

_TOOL_GUIDANCE_CLOSING = (
    "Only call a tool when it is actually required or clearly adds value — "
    "never invent tool results, never call a tool pointlessly, and if a tool "
    "is unavailable, handle it gracefully and continue the conversation. "
    "Never expose tool names, IDs, or internal details to the customer; speak "
    "naturally about outcomes (\"I've scheduled that\", \"here's what I found\")."
)

# (gate capability keys, bullet). A bullet is included when ANY of its gated
# capability rows is not unavailable (see _CAPABILITY_ROWS keys); an empty gate
# means the bullet is always included.
_TOOL_GUIDANCE_BULLETS: list[tuple[tuple[str, ...], str]] = [
    (
        ("scheduling",),
        "- Book, reschedule, or cancel a meeting the moment the customer agrees, "
        "and check availability before promising a time.",
    ),
    (
        ("meeting_intelligence",),
        "- When the customer mentions a past meeting or asks about a recording, "
        "transcript, or summary, search and pull the relevant meeting assets "
        "instead of guessing.",
    ),
    (
        (),
        "- Check the product catalog / inventory before quoting details.",
    ),
    (
        ("prospect_search", "crm"),
        "- Use prospect / CRM data to personalize the conversation.",
    ),
]


def connected_tools_guidance(company_id: int) -> str:
    """Tailored '### CONNECTED TOOLS' block for the voice system prompt.

    Bullets are included only when the company actually has the capability they
    describe — e.g. the meeting-recordings bullet is dropped when Zoom isn't
    connected. The full untailored block (every bullet) is the
    CONNECTED_TOOLS_GUIDANCE constant in voice_agent_runtime_service.py, used
    as the fail-open fallback when detection fails — keep both in sync if a
    bullet is ever added or reworded.
    """
    info = _detect(company_id)
    rows = {r["key"]: r for r in (_row_analysis(row, info) for row in _CAPABILITY_ROWS)}
    bullets: list[str] = []
    for gate_keys, bullet in _TOOL_GUIDANCE_BULLETS:
        if not gate_keys or any(rows[k]["status"] != "unavailable" for k in gate_keys):
            bullets.append(bullet)
    return (
        f"{_TOOL_GUIDANCE_HEADER}\n"
        + "\n".join(bullets)
        + f"\n{_TOOL_GUIDANCE_CLOSING}"
    )


def connected_providers_context(company_id: int, include_directive: bool = True) -> str:
    """Per-company 'CONNECTED PROVIDERS' block for system prompts.

    Returns '' when no external provider is connected (so the caller can skip
    the block entirely). Only rows that are available/degraded are listed; the
    priority order shown is the provider order in the row itself.

    ``include_directive=True`` (default, voice calls) uses the customer-facing
    'use them proactively' framing. ``include_directive=False`` (non-voice
    agents like researcher/post_call/ism, whose toolsets can't invoke these
    providers directly) uses a neutral framing: the integrations are context
    that may inform decisions, not tools to call.
    """
    info = _detect(company_id)

    # A bare account (only built-in providers like the DB product catalog) has
    # no external integrations: return "" so the caller injects the short
    # honesty guard instead of generic tool guidance the agent can't use.
    if not (info["connected"] - _BUILTIN_PROVIDERS):
        return ""

    lines: list[str] = []
    for row in _CAPABILITY_ROWS:
        analysis = _row_analysis(row, info)
        if analysis["status"] == "unavailable":
            continue
        parts = []
        for p in analysis["providers"]:
            if p["state"] == "connected":
                parts.append(f"{p['label']} ✓")
            elif p["state"] == "degraded":
                parts.append(f"{p['label']} (meeting:write missing — creation hidden)")
        if not parts:
            continue
        lines.append(f"- {analysis['label']}: {', '.join(parts)}")

    if not lines:
        return ""

    if include_directive:
        intro = (
            "These providers are live for this company — use them proactively "
            "when they genuinely help the customer, and never use a provider "
            "that isn't listed:"
        )
        closing = (
            "When more than one provider is listed for a need, use them in the "
            "priority order shown (first listed = preferred); if the first "
            "fails, fall back to the next one listed."
        )
    else:
        intro = (
            "These integrations are connected for this company and may inform "
            "your decisions — you can only call the tools in your own toolset, "
            "never invoke these integrations directly:"
        )
        closing = (
            "When more than one provider is listed, the order shown is the "
            "company's preference."
        )

    return (
        "### CONNECTED PROVIDERS\n"
        f"{intro}\n"
        + "\n".join(lines)
        + f"\n{closing}"
    )


def agent_system_prompt(base: str, company_id: int) -> str:
    """Append the per-company CONNECTED PROVIDERS block to an agent prompt.

    Shared by the non-voice agents (researcher, post_call, ism) so they know
    which providers are live for this company and the priority order between
    overlapping ones — same truth as the voice-call prompt and the Settings
    card. Returns ``base`` unchanged when nothing external is connected (no
    dead tokens, and the caller's own "no tools" behavior applies).
    """
    # Neutral framing (include_directive=False): these internal agents can't
    # call the listed providers directly, so don't tell them to 'use them
    # proactively' — the integrations are context that may inform decisions.
    connected = connected_providers_context(company_id, include_directive=False)
    if not connected:
        return base
    return f"{base}\n\n{connected}"


def build_capabilities_summary(company_id: int) -> dict:
    """JSON 'effective capabilities' payload for the Settings card."""
    info = _detect(company_id)
    return {
        "connected_providers": sorted(info["connected"]),
        # False when only built-ins (e.g. the DB product catalog) are available
        # — lets the Settings card show a 'bare account' banner.
        "external_connected": bool(info["connected"] - _BUILTIN_PROVIDERS),
        "meeting_write_granted": info["zoom_write_granted"],
        "capabilities": [_row_analysis(row, info) for row in _CAPABILITY_ROWS],
    }
