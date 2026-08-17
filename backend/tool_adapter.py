import asyncio
import logging
import re
from typing import Any

from sqlmodel import Session


# LLM tool-call argument coercion.  Different LLMs handle the same
# function-schema field types differently:
#   - Mistral / GPT-class: clean int or numeric string ("110", 110)
#   - Cerebras Llama 3.1 8B: free-form English ("less than 10", "lead 110", "10%")
#
# Strategy: try the fast path (int()/float()), fall back to regex extraction
# from the string form.  Never reject — pass the result downstream so the
# real tool decides what "valid" means (lead-not-found, etc.).  Keeps the
# original behavior intact for compliant LLMs while catching the messy ones.

def _safe_int_arg(raw: Any, default: int = 0) -> int:
    """Tolerant int coercion for LLM tool args.  Tries int() first; on
    failure, regex-extracts the first integer from the string form.  Returns
    `default` only when nothing numeric is present at all.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    s = str(raw).strip()
    if not s:
        return default
    try:
        return int(s)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+", s)
        return int(m.group(0)) if m else default


def _safe_float_arg(raw: Any, default: float = 0.0) -> float:
    """Tolerant float coercion.  Strips '%', '$', whitespace; extracts the
    first numeric token from strings like '10.5%' or 'discount 15'.  Returns
    `default` only when nothing numeric is present.
    """
    if raw is None:
        return default
    if isinstance(raw, bool):
        return float(raw)
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().replace("%", "").replace("$", "").strip()
    if not s:
        return default
    try:
        return float(s)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group(0)) if m else default

from database import engine
from services.agent.agent_tool_service import (
    book_demo,
    book_meeting,
    check_guardrails,
    check_icp_qualification,
    get_call_latency_summary,
    get_google_auth_url,
    get_or_create_lead,
    get_product_info,
    get_user_or_404,
    send_communication,
    submit_google_auth_code,
    sync_product_catalog,
)

logger = logging.getLogger(__name__)


_ALL_TOOLS: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "check_icp_qualification",
                "description": "Validate whether a prospect fits the ideal customer profile.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "company_size": {"type": "string"},
                        "industry": {"type": "string"},
                        # anyOf accepts both integer and string from any LLM.
                        # Execution coerces via _safe_int_arg regardless of type.
                        "employee_count": {"anyOf": [{"anyOf": [{"type": "integer"}, {"type": "string"}]}, {"type": "string"}]},
                    },
                    "required": ["company_size", "industry", "employee_count"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_product_info",
                "description": "Fetch product details from the tenant's product catalog.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "product_name": {"type": "string"},
                    },
                    "required": ["product_name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_guardrails",
                "description": "Check whether a requested discount is inside policy.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "requested_discount_percent": {"type": "number"},
                    },
                    "required": ["requested_discount_percent"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "book_meeting",
                "description": "Create an appointment for a lead and optionally send confirmation email.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                        "proposed_time": {"type": "string", "description": "Lead-local ISO 8601 datetime with no timezone suffix; never append Z or a UTC offset."},
                        "meeting_type": {"type": "string"},
                        "lead_email": {"type": "string"},
                    },
                    "required": ["lead_id", "proposed_time", "meeting_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_call_latency_summary",
                "description": "Return latency summary when analytics migration is available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "interaction_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    },
                    "required": ["interaction_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_or_create_lead",
                "description": "Find an existing lead by phone/email or create one in the current tenant.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "email": {"type": "string"},
                    },
                    "required": ["name", "phone"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "sync_product_catalog",
                "description": "Sync the current tenant's product catalog to the semantic index.",
                "parameters": {
                    "type": "object",
                    "properties": {},
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "schedule_demo",
                "description": "Authoritatively schedule a lead demo through the company's connected scheduling provider. Loads the lead, resolves its timezone, persists one appointment, creates the provider meeting, sends one confirmation, and returns the persisted appointment. Do not call send_communication afterward for the same demo.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                        "requested_time": {"type": "string", "description": "Lead-local natural language such as 'tomorrow at 10 AM', or lead-local ISO without an offset."},
                        "products": {"type": "string"},
                        "demo_type": {"type": "string", "description": "Online or Offline."},
                        "duration_minutes": {"type": "integer", "description": "Duration in minutes; default 30."},
                        "provider": {"type": "string", "description": "Optional provider preference; otherwise use the company's connected-provider priority."},
                        "notes": {"type": "string"},
                    },
                    "required": ["lead_id", "requested_time", "products", "demo_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "book_demo",
                "description": "Compatibility alias for schedule_demo. Book a demo through the company's connected scheduling provider and send one confirmation. Do not assume Google Calendar or call send_communication afterward.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                        "name": {"type": "string"},
                        "phone": {"type": "string"},
                        "demo_date": {"type": "string", "description": "Lead-local ISO 8601 start datetime, with no timezone suffix. Example: if the lead says tomorrow at 10 AM in their local timezone, send 2026-08-14T10:00:00. Never append Z or a UTC offset."},
                        "products": {"type": "string"},
                        "demo_type": {"type": "string", "description": "Online or Offline. The connected provider determines the meeting link."},
                        "provider": {"type": "string", "description": "Optional scheduling provider preference. Leave empty to use the company's connected-provider priority; do not assume Google."},
                        "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 30)."},
                        "city": {"type": "string"},
                        "state": {"type": "string"},
                        "pincode": {"type": "string"},
                        "email": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["lead_id", "name", "phone", "demo_date", "products", "demo_type"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "send_communication",
                "description": "Send an email and/or WhatsApp message to a lead.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "lead_id": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                        "channels": {
                            "type": "array",
                            "items": {"type": "string", "enum": ["email", "whatsapp"]},
                        },
                        "content": {"type": "string"},
                        "subject": {"type": "string"},
                        "email": {"type": "string"},
                        "phone": {"type": "string"},
                    },
                    "required": ["lead_id", "channels", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_google_auth_url",
                "description": "Return Google Calendar auth status for the current tenant-safe path.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "submit_google_auth_code",
                "description": "Submit a Google auth code when calendar auth migration is available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "code": {"type": "string"},
                    },
                    "required": ["code"],
                },
            },
        },

        {
            "type": "function",
            "function": {
                "name": "warm_transfer",
                "description": "Transfer the current call to a human agent in a real conference bridge. The customer and the human agent can talk to each other live. Use when the customer asks to speak to a person about pricing, discounts, or escalated issues — and one or more agents are available.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "transfer_to_number": {
                            "type": "string",
                            "description": "Optional fallback E.164 phone number only if explicitly provided by system context. The configured Settings number is preferred.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief reason for the transfer (shown to the human agent). Examples: 'customer asked for discount approval', 'escalation — customer is unhappy', 'technical question beyond my knowledge'.",
                        },
                    },
                },
            },
        },
    ]


# ── Connector / capability tools (backed by the MCP capability router) ──────── #
# These unlock the connected apps: Apollo/RocketReach prospect search, Zoho CRM,
# Cal.com/Calendly scheduling, and inventory lookup/reserve. They are resolved at
# runtime by services.mcp.capability_router.route_capability().

_CAPABILITY_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search_prospects",
            "description": "Search a connected prospect database (Apollo.io, HubSpot contacts, or RocketReach) for new leads matching a profile. Provider priority: Apollo → HubSpot → RocketReach (pass 'provider' to override). Use when the user asks to find people, build a prospect list, or gather contact details for outreach.",
            "parameters": {
                "type": "object",
                "properties": {
                    "person_title": {"type": "string", "description": "Job title filter, e.g. 'Head of Sales' or 'CTO'."},
                    "industry": {"type": "string", "description": "Industry filter, e.g. 'Software' or 'Healthcare'."},
                    "location": {"type": "string", "description": "Location filter, e.g. 'India' or 'Bengaluru'."},
                    "company_size": {"type": "string", "description": "Company size range filter, e.g. '11-50'."},
                    "seniority": {"type": "string", "description": "Seniority filter, e.g. 'director', 'vp', 'c_level'."},
                    "limit": {"type": "integer", "description": "Max results to return (default 10)."},
                    "provider": {"type": "string", "description": "Preferred provider: 'apollo', 'hubspot', or 'rocketreach_mcp'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enrich_prospect",
            "description": "Enrich a prospect with verified email, phone, LinkedIn URL, title, and company size from a connected data provider (Apollo/RocketReach). Provide an email, or name + company_name together.",
            "parameters": {
                "type": "object",
                "properties": {
                    "email": {"type": "string", "description": "Known email address of the person to enrich."},
                    "name": {"type": "string", "description": "Full name of the person (use with company_name if email is unknown)."},
                    "company_name": {"type": "string", "description": "Company the person works at (use with name if email is unknown)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_crm_contact",
            "description": "Create a contact or lead in the connected CRM (Zoho or HubSpot). Provider priority: Zoho → HubSpot (pass 'provider' to override). Use when a lead/contact should be saved to the company's CRM.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "company": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string", "description": "Notes or context about the contact."},
                    "provider": {"type": "string", "description": "Preferred CRM: 'zoho' or 'hubspot'."},
                },
            },
            "required": ["name"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_crm_contact",
            "description": "Update an existing contact in the connected CRM (Zoho or HubSpot) by record id. Provider priority: Zoho → HubSpot (pass 'provider' to override).",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_id": {"type": "string", "description": "CRM record id of the contact to update."},
                    "data": {"type": "object", "description": "Field map with the values to update, e.g. {'phone': '+91...'}."},
                    "provider": {"type": "string", "description": "Preferred CRM: 'zoho' or 'hubspot'."},
                },
            },
            "required": ["record_id", "data"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "crm_query",
            "description": "Query records in the connected CRM (Zoho or HubSpot) using a query string or module. Provider priority: Zoho → HubSpot (pass 'provider' to override).",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Query string (e.g. COQL for Zoho, free text for HubSpot search)."},
                    "module": {"type": "string", "description": "CRM module/object, e.g. Contacts (Zoho) or contacts/companies/deals (HubSpot)."},
                    "provider": {"type": "string", "description": "Preferred CRM: 'zoho' or 'hubspot'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "enroll_sequence",
            "description": "Enroll a contact into an outreach sequence in the connected engagement platform (e.g. Apollo).",
            "parameters": {
                "type": "object",
                "properties": {
                    "contact_id": {"type": "string"},
                    "sequence_id": {"type": "string"},
                },
            },
            "required": ["contact_id", "sequence_id"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "outreach_analytics",
            "description": "Pull analytics/reports from the connected outreach platform (e.g. Apollo).",
            "parameters": {
                "type": "object",
                "properties": {
                    "report_name": {"type": "string", "description": "Which report or metric to fetch."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_lookup",
            "description": "Look up a product's stock and details across the company's connected inventory sources by SKU.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "location": {"type": "string", "description": "Optional warehouse/location filter."},
                },
            },
            "required": ["sku"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "inventory_reserve",
            "description": "Reserve quantity of a product by SKU across connected inventory sources.",
            "parameters": {
                "type": "object",
                "properties": {
                    "sku": {"type": "string"},
                    "qty": {"type": "integer"},
                },
            },
            "required": ["sku", "qty"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "schedule_meeting",
            "description": "Schedule a meeting/demo on the connected scheduling app. Provider priority: Cal.com → Calendly → Microsoft 365 → Google Calendar (auto-falls back to Google Calendar + Meet link when no external scheduler is connected; pass 'provider' to override). Use when the customer agrees to book a meeting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "event_type_id": {"type": "string", "description": "Scheduling link / event type id to book against (Cal.com/Calendly)."},
                    "start_time": {"type": "string", "description": "ISO 8601 start datetime, e.g. 2026-08-10T15:00:00."},
                    "invitee_email": {"type": "string"},
                    "invitee_name": {"type": "string"},
                    "notes": {"type": "string"},
                    "subject": {"type": "string", "description": "Event subject (used by Microsoft 365 calendar)."},
                    "end_time": {"type": "string", "description": "ISO 8601 end datetime (optional; Microsoft 365 calendar)."},
                    "provider": {"type": "string", "description": "Preferred provider: 'calcom', 'calendly', or 'microsoft'."},
                },
            },
            "required": ["start_time"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_availability",
            "description": "Check available slots on the connected scheduling app. Provider priority: Cal.com → Calendly → Microsoft 365 → Google Calendar (auto-falls back to Google Calendar when no external scheduler is connected; pass 'provider' to override).",
            "parameters": {
                "type": "object",
                "properties": {
                    "date": {"type": "string", "description": "Date to check, YYYY-MM-DD."},
                    "event_type_id": {"type": "string"},
                    "provider": {"type": "string", "description": "Preferred provider: 'calcom', 'calendly', or 'microsoft'."},
                },
            },
            "required": ["date"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_bookings",
            "description": "List existing bookings/events from the connected scheduling app. Provider priority: Cal.com → Calendly → Microsoft 365 → Google Calendar (pass 'provider' to override).",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "Filter by status, e.g. active, canceled."},
                    "from_date": {"type": "string"},
                    "to_date": {"type": "string"},
                    "provider": {"type": "string", "description": "Preferred provider: 'calcom', 'calendly', or 'microsoft'."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reschedule_meeting",
            "description": "Reschedule an existing booking on the connected scheduling app. Provider priority: Cal.com → Calendly → Microsoft 365 → Google Calendar (pass 'provider' to override).",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "new_start_time": {"type": "string", "description": "ISO 8601 new start datetime."},
                    "end_time": {"type": "string", "description": "ISO 8601 new end datetime (optional; Microsoft 365 calendar)."},
                    "provider": {"type": "string", "description": "Preferred provider: 'calcom', 'calendly', or 'microsoft'."},
                },
            },
            "required": ["booking_id", "new_start_time"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_meeting",
            "description": "Cancel an existing booking on the connected scheduling app. Provider priority: Cal.com → Calendly → Microsoft 365 → Google Calendar (pass 'provider' to override).",
            "parameters": {
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "reason": {"type": "string"},
                    "provider": {"type": "string", "description": "Preferred provider: 'calcom', 'calendly', or 'microsoft'."},
                },
            },
            "required": ["booking_id"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_microsoft_email",
            "description": "Send an email from the company's connected Microsoft 365 (Outlook) mailbox using Microsoft Graph. Use when the user wants an email sent from their Microsoft account — e.g. sending the quote, meeting notes, or a follow-up from Outlook.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to_email": {"type": "string", "description": "Recipient email address."},
                    "subject": {"type": "string"},
                    "body": {"type": "string", "description": "Plain-text message body."},
                    "cc_email": {"type": "string"},
                },
            },
            "required": ["to_email", "subject"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_meeting",
            "description": "Create a Zoom meeting via the Zoom REST API and return a join URL. This is the auto-fallback meeting-link provider for bookings when Google Calendar is not connected — the booking flow prefers a Google Meet link, then falls back to a Zoom link. Requires the connected Zoom app to have the 'meeting:write' scope.",
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "Meeting title."},
                    "start_time": {"type": "string", "description": "ISO 8601 start datetime."},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 30)."},
                    "attendee_email": {"type": "string"},
                },
            },
            "required": ["topic"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_meetings",
            "description": "Search Zoom meetings for the connected account by topic or host, optionally within a date range. Use to locate a past or upcoming meeting before pulling its assets or recordings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search key — meeting topic or host email/name."},
                    "from_date": {"type": "string", "description": "Start of the search window, YYYY-MM-DD."},
                    "to_date": {"type": "string", "description": "End of the search window, YYYY-MM-DD."},
                    "page_size": {"type": "integer", "description": "Max results per page (default 10)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_meeting_assets",
            "description": "Retrieve the assets available for a Zoom meeting — summaries, transcripts, cloud recordings, whiteboards, and docs. Use after locating the meeting via search_meetings.",
            "parameters": {
                "type": "object",
                "properties": {
                    "meeting_id": {"type": "string", "description": "Zoom meeting UUID or ID."},
                },
            },
            "required": ["meeting_id"],
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_meeting_recordings",
            "description": "List cloud recordings for the connected Zoom account, optionally filtered by date range.",
            "parameters": {
                "type": "object",
                "properties": {
                    "from_date": {"type": "string", "description": "Start date, YYYY-MM-DD."},
                    "to_date": {"type": "string", "description": "End date, YYYY-MM-DD."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recording_resource",
            "description": "Fetch download information and URLs for a specific cloud recording resource of a Zoom meeting.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recording_id": {"type": "string", "description": "Recording UUID."},
                },
            },
            "required": ["recording_id"],
        },
    },
]

_ALL_TOOLS.extend(_CAPABILITY_TOOLS)


def get_mistral_tools(
    company_id: int | None = None,
    agent_id: int | None = None,
) -> list[dict[str, Any]]:
    """Return LLM function schemas, optionally filtered to a company's enabled tools.

    When ``company_id`` is None, the full catalog is returned (legacy callers). When a
    company_id is supplied, the list is filtered to the tools that company has enabled
    — always-on groups plus integrations it has actually connected (MCP servers,
    inventory sources, etc.). This is what makes connected apps discoverable to the
    voice agent and other LLM-driven flows.

    When ``agent_id`` is supplied and the agent has active VoiceAgentTool rows,
    the list is further restricted to the agent's allowlist — but CORE_TOOL_NAMES
    (product info, ICP check, guardrails, lead create, warm transfer, etc.) always
    stay available so per-agent gating can never silently cripple a conversation.
    An agent with no tool rows is unrestricted (falls back to the company set).
    """
    if company_id is None:
        return list(_ALL_TOOLS)

    try:
        from mcp_tools.tool_catalog import CORE_TOOL_NAMES, agent_tool_names, tool_names_for_company
        enabled = tool_names_for_company(company_id)
        if agent_id is not None:
            allowed = agent_tool_names(company_id, agent_id)
            if allowed:
                # Gate domain tools to the allowlist; keep core conversation tools
                # (intersected with the company set so we never inject a tool the
                # company hasn't enabled).
                enabled = (enabled & allowed) | (CORE_TOOL_NAMES & enabled)
        return [t for t in _ALL_TOOLS if t["function"]["name"] in enabled]
    except Exception:
        logger.warning(
            "[tool_adapter] tool filtering failed for company %s agent %s — returning full list",
            company_id,
            agent_id,
            exc_info=True,
        )
        return list(_ALL_TOOLS)


async def _execute_with_session(
    session: Session,
    tool_name: str,
    arguments: dict[str, Any],
    user_id: int | None,
    interaction_id: str | None = None,
) -> dict[str, Any]:
    if tool_name == "lookup_product":
        tool_name = "get_product_info"

    if tool_name == "check_icp_qualification":
        return check_icp_qualification(
            company_size=arguments.get("company_size", ""),
            industry=arguments.get("industry", ""),
            employee_count=_safe_int_arg(arguments.get("employee_count")),
        )

    if not user_id:
        return {
            "error": "Authenticated user context is required for tenant-safe tool execution.",
            "tool": tool_name,
        }

    user = get_user_or_404(session, user_id)
    company_id = user.company_id

    # get_product_info must run before the dispatcher — the dispatcher calls it
    # with an incompatible signature (actor_user_id) and swallows the result.
    if tool_name == "get_product_info":
        product_name = arguments.get("product_name", "")
        logger.info("[tool_adapter] get_product_info: searching for %r (company=%s)", product_name, company_id)
        from services.inventory.factory import build_inventory_service
        inv = await build_inventory_service(session, company_id)
        results = await inv.search(product_name)
        if results:
            logger.info("[tool_adapter] get_product_info: HIT via inventory service: %s", results[0].get("name"))
            return results[0]
        logger.info("[tool_adapter] get_product_info: no inventory hit, falling back to DB")
        return get_product_info(
            session=session,
            company_id=company_id,
            product_name=product_name,
        )

    if tool_name == "check_guardrails":
        return check_guardrails(
            requested_discount_percent=_safe_float_arg(arguments.get("requested_discount_percent")),
        )

    if tool_name == "book_meeting":
        return await book_meeting(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=_safe_int_arg(arguments.get("lead_id")),
            proposed_time=arguments.get("proposed_time", ""),
            meeting_type=arguments.get("meeting_type", "demo"),
            lead_email=arguments.get("lead_email"),
        )

    if tool_name == "get_call_latency_summary":
        return get_call_latency_summary(
            interaction_id=_safe_int_arg(arguments.get("interaction_id")),
        )

    if tool_name == "get_or_create_lead":
        return get_or_create_lead(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            name=arguments.get("name", ""),
            phone=arguments.get("phone", ""),
            email=arguments.get("email"),
        )

    if tool_name == "sync_product_catalog":
        return sync_product_catalog(
            session=session,
            company_id=company_id,
        )

    if tool_name in {"book_demo", "schedule_demo"}:
        return await book_demo(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=_safe_int_arg(arguments.get("lead_id")),
            name=arguments.get("name", ""),
            phone=arguments.get("phone", ""),
            city=arguments.get("city"),
            state=arguments.get("state"),
            pincode=arguments.get("pincode"),
            demo_date=arguments.get("demo_date") or arguments.get("requested_time", ""),
            products=arguments.get("products", ""),
            demo_type=arguments.get("demo_type", "Offline"),
            provider=arguments.get("provider"),
            duration_minutes=_safe_int_arg(arguments.get("duration_minutes"), 30),
            email=arguments.get("email"),
            notes=arguments.get("notes"),
        )

    if tool_name == "send_communication":
        return send_communication(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=_safe_int_arg(arguments.get("lead_id")),
            channels=list(arguments.get("channels") or []),
            content=arguments.get("content", ""),
            subject=arguments.get("subject"),
            email=arguments.get("email"),
            phone=arguments.get("phone"),
        )

    if tool_name == "get_google_auth_url":
        return get_google_auth_url(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
        )

    if tool_name == "submit_google_auth_code":
        return submit_google_auth_code(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            code=arguments.get("code", ""),
        )



    if tool_name == "warm_transfer":
        from credentials_service import get_company_setting_value, get_user_setting_value

        user_transfer_to = get_user_setting_value(session, user.id, "WARM_TRANSFER_NUMBER") or ""
        user_transfer_name = get_user_setting_value(session, user.id, "WARM_TRANSFER_NAME") or ""
        company_transfer_to = get_company_setting_value(session, company_id, "WARM_TRANSFER_NUMBER") or ""
        company_transfer_name = get_company_setting_value(session, company_id, "WARM_TRANSFER_NAME") or ""
        configured_transfer_to = user_transfer_to or company_transfer_to
        configured_transfer_name = user_transfer_name or company_transfer_name
        transfer_to = configured_transfer_to
        reason = arguments.get("reason") or ""
        if not transfer_to:
            return {
                "error": "Warm transfer number is not configured. Add WARM_TRANSFER_NUMBER in Settings > Integration Keys or My Email > My Warm Transfer.",
                "tool": "warm_transfer",
            }
        try:
            from services.call.warm_transfer_service import execute_warm_transfer
            interaction_id_int = int(interaction_id) if interaction_id else 0
            return execute_warm_transfer(
                session=session,
                company_id=company_id,
                actor_user_id=user.id,
                interaction_id=interaction_id_int,
                transfer_to=transfer_to,
                isr_name=configured_transfer_name,
                transfer_to_name=configured_transfer_name,
                reason=reason,
            )
        except Exception as exc:
            logger.error("[warm_transfer] Failed: %s", exc, exc_info=True)
            return {"error": f"Warm transfer failed: {exc}", "tool": "warm_transfer"}

    # ── Dispatcher fast-path: delegate to registry if tool is registered ──────
    try:
        from mcp_tools.dispatcher import ToolDispatcher
        dispatcher = ToolDispatcher.get()
        if tool_name in dispatcher.registry.list_all():
            int_id = int(interaction_id) if interaction_id and str(interaction_id).isdigit() else None
            return await dispatcher.dispatch(
                tool_name,
                arguments,
                company_id=company_id,
                user_id=user_id,
                interaction_id=int_id,
            )
    except Exception as _disp_exc:
        logger.warning("[tool_adapter] dispatcher check failed, falling through: %s", _disp_exc)
    # ─────────────────────────────────────────────────────────────────────────

    if tool_name == "get_call_latency_summary":
        return get_call_latency_summary(
            interaction_id=_safe_int_arg(arguments.get("interaction_id")),
        )

    if tool_name == "get_or_create_lead":
        return get_or_create_lead(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            name=arguments.get("name", ""),
            phone=arguments.get("phone", ""),
            email=arguments.get("email"),
        )

    if tool_name == "sync_product_catalog":
        return sync_product_catalog(
            session=session,
            company_id=company_id,
        )

    if tool_name in {"book_demo", "schedule_demo"}:
        return await book_demo(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=_safe_int_arg(arguments.get("lead_id")),
            name=arguments.get("name", ""),
            phone=arguments.get("phone", ""),
            city=arguments.get("city"),
            state=arguments.get("state"),
            pincode=arguments.get("pincode"),
            demo_date=arguments.get("demo_date") or arguments.get("requested_time", ""),
            products=arguments.get("products", ""),
            demo_type=arguments.get("demo_type", "Offline"),
            provider=arguments.get("provider"),
            duration_minutes=_safe_int_arg(arguments.get("duration_minutes"), 30),
            email=arguments.get("email"),
            notes=arguments.get("notes"),
        )

    if tool_name == "send_communication":
        return send_communication(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            lead_id=_safe_int_arg(arguments.get("lead_id")),
            channels=list(arguments.get("channels") or []),
            content=arguments.get("content", ""),
            subject=arguments.get("subject"),
            email=arguments.get("email"),
            phone=arguments.get("phone"),
        )

    if tool_name == "get_google_auth_url":
        return get_google_auth_url(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
        )

    if tool_name == "submit_google_auth_code":
        return submit_google_auth_code(
            session=session,
            company_id=company_id,
            actor_user_id=user.id,
            code=arguments.get("code", ""),
        )



    if tool_name == "warm_transfer":
        from credentials_service import get_company_setting_value, get_user_setting_value

        user_transfer_to = get_user_setting_value(session, user.id, "WARM_TRANSFER_NUMBER") or ""
        user_transfer_name = get_user_setting_value(session, user.id, "WARM_TRANSFER_NAME") or ""
        company_transfer_to = get_company_setting_value(session, company_id, "WARM_TRANSFER_NUMBER") or ""
        company_transfer_name = get_company_setting_value(session, company_id, "WARM_TRANSFER_NAME") or ""
        configured_transfer_to = user_transfer_to or company_transfer_to
        configured_transfer_name = user_transfer_name or company_transfer_name
        transfer_to = configured_transfer_to
        reason = arguments.get("reason") or ""
        if not transfer_to:
            return {
                "error": "Warm transfer number is not configured. Add WARM_TRANSFER_NUMBER in Settings > Integration Keys or My Email > My Warm Transfer.",
                "tool": "warm_transfer",
            }
        try:
            from services.call.warm_transfer_service import execute_warm_transfer
            interaction_id_int = int(interaction_id) if interaction_id else 0
            return execute_warm_transfer(
                session=session,
                company_id=company_id,
                actor_user_id=user.id,
                interaction_id=interaction_id_int,
                transfer_to=transfer_to,
                isr_name=configured_transfer_name,
                transfer_to_name=configured_transfer_name,
                reason=reason,
            )
        except Exception:
            logger.exception("[warm_transfer] Failed", exc_info=True)
            return {"error": "Warm transfer failed — please try again.", "tool": "warm_transfer"}

    # Route named business capabilities through the capability router
    from services.mcp.capability_router import CAPABILITY_MAP, route_capability
    if tool_name in CAPABILITY_MAP:
        return await route_capability(
            session=session,
            company_id=company_id,
            capability=tool_name,
            arguments=arguments,
            user_id=user_id,
        )

    # Route "<server>__<tool>" calls to the external MCP client
    if "__" in tool_name:
        prefix, ext_tool = tool_name.split("__", 1)
        from services.platform.mcp_client import call_external_tool, EXTERNAL_MCP_SERVERS
        if prefix in EXTERNAL_MCP_SERVERS:
            return await call_external_tool(
                prefix=prefix,
                tool_name=ext_tool,
                arguments=arguments,
            )

    return {
        "error": "Unknown tool",
        "tool": tool_name,
        "available_tools": [tool["function"]["name"] for tool in get_mistral_tools()],
    }


async def execute_mcp_tool(
    tool_name: str,
    arguments: dict[str, Any],
    interaction_id: str | None = None,
    user_id: int | None = None,
    user=None,
    session: Session | None = None,
) -> dict[str, Any]:
    import time
    logger.info(
        "[execute_mcp_tool] tool=%s interaction_id=%s user_id=%s args=%s",
        tool_name,
        interaction_id,
        user_id,
        arguments,
    )

    _start = time.monotonic()
    _status = "success"
    _error: str | None = None

    try:
        async with asyncio.timeout(30):
            if session is not None:
                effective_user_id = user_id or getattr(user, "id", None)
                result = await _execute_with_session(session, tool_name, arguments, effective_user_id, interaction_id=interaction_id)
            else:
                with Session(engine) as owned_session:
                    effective_user_id = user_id or getattr(user, "id", None)
                    result = await _execute_with_session(owned_session, tool_name, arguments, effective_user_id, interaction_id=interaction_id)
            if result.get("error"):
                _status = "error"
                _error = str(result["error"])[:500]
            return result
    except asyncio.TimeoutError:
        _status = "timeout"
        _error = f"timed out after 30s"
        logger.error("[execute_mcp_tool] Tool '%s' timed out after 30s", tool_name)
        return {"error": f"Tool '{tool_name}' timed out — please try again.", "tool": tool_name}
    except Exception as exc:
        _status = "error"
        _error = str(exc)[:500]
        logger.error("[execute_mcp_tool] Tool execution failed for %s: %s", tool_name, exc, exc_info=True)
        return {
            "error": f"Tool execution failed: {exc}",
            "tool": tool_name,
        }
    finally:
        _dur_ms = int((time.monotonic() - _start) * 1000)
        try:
            _eid = effective_user_id if "effective_user_id" in dir() else None
            _cid: int | None = None
            if _eid:
                try:
                    with Session(engine) as _s:
                        from models.models import User as _U
                        from sqlmodel import select as _sel
                        _u = _s.exec(_sel(_U).where(_U.id == _eid)).first()
                        _cid = _u.company_id if _u else None
                except Exception:
                    pass
            if _cid:
                from services.observability.tool_call_tracer import trace_tool_call as _trace
                asyncio.create_task(_trace(
                    tool_name=tool_name,
                    company_id=_cid,
                    status=_status,
                    duration_ms=_dur_ms,
                    user_id=_eid,
                    interaction_id=int(interaction_id) if interaction_id and str(interaction_id).isdigit() else None,
                    error_message=_error,
                ))
        except Exception:
            pass
