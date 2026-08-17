"""
capabilities.py - ToolSpecs for connector-backed capability tools.

These tools are resolved at runtime by services.mcp.capability_router.route_capability()
against the company's connected MCP servers (Apollo, RocketReach, Zoho, Cal.com,
Calendly) and inventory sources. Registering them in the ToolRegistry makes them
dispatchable via the ToolDispatcher and visible to build_tool_context_string(),
so agent flows beyond the voice pipeline can use connected apps too.
"""
from __future__ import annotations

from mcp_tools.spec import ToolSpec

# JSON-schema parameter shapes mirror the LLM schemas in tool_adapter._CAPABILITY_TOOLS
_SEARCH_PROSPECTS_PARAMS = {
    "type": "object",
    "properties": {
        "person_title": {"type": "string", "description": "Job title filter, e.g. Head of Sales."},
        "industry": {"type": "string", "description": "Industry filter, e.g. Software."},
        "location": {"type": "string", "description": "Location filter, e.g. India."},
        "company_size": {"type": "string", "description": "Company size range, e.g. 11-50."},
        "seniority": {"type": "string", "description": "Seniority, e.g. director, vp, c_level."},
        "limit": {"type": "integer", "description": "Max results (default 10)."},
    },
}

_ENRICH_PROSPECT_PARAMS = {
    "type": "object",
    "properties": {
        "email": {"type": "string"},
        "name": {"type": "string"},
        "company_name": {"type": "string"},
    },
}

_SCHEDULING_PARAMS = {
    "type": "object",
    "properties": {
        "event_type_id": {"type": "string", "description": "Scheduling link / event type id (Cal.com/Calendly)."},
        "start_time": {"type": "string", "description": "ISO 8601 start datetime."},
        "invitee_email": {"type": "string"},
        "invitee_name": {"type": "string"},
        "notes": {"type": "string"},
        "subject": {"type": "string", "description": "Event subject (used by Microsoft 365 calendar)."},
        "end_time": {"type": "string", "description": "ISO 8601 end datetime (optional; Microsoft 365 calendar)."},
        "provider": {"type": "string", "description": "Preferred provider to use, e.g. 'calcom', 'calendly', 'microsoft'. Defaults to the documented priority order (Cal.com → Calendly → Microsoft 365)."},
    },
}

# Optional provider override shared by multi-provider capabilities. The router
# honours it by trying the named provider first, then the documented fallback
# chain (see services/mcp/capability_router.PROVIDER_PRIORITY).
_PROVIDER_PARAM = {
    "provider": {"type": "string", "description": "Preferred provider, e.g. 'hubspot' or 'zoho' (CRM), 'apollo' (search), 'microsoft' (scheduling/email). Defaults to the documented priority order."},
}

_CAPABILITY_SPECS: dict[str, ToolSpec] = {
    "search_prospects": ToolSpec(
        name="search_prospects",
        category="integrations",
        description=(
            "Search connected prospect databases (Apollo.io or RocketReach) for new "
            "leads matching a target profile and return contact details."
        ),
        when_to_use=[
            "The user asks to find new prospects or build a lead list",
            "A campaign or call list needs fresh contacts for a profile",
        ],
        when_not_to_use=[
            "No prospect database is connected (Apollo / RocketReach)",
            "The user wants details on a specific known person — use enrich_prospect",
        ],
        returns="List of prospects with name, title, company, email, phone, LinkedIn URL.",
        parameters={
            "type": "object",
            "properties": {
                **_SEARCH_PROSPECTS_PARAMS["properties"],
                **_PROVIDER_PARAM,
            },
        },
    ),
    "enrich_prospect": ToolSpec(
        name="enrich_prospect",
        category="integrations",
        description=(
            "Enrich a known person with verified email, phone, LinkedIn, title, and "
            "company size from a connected data provider."
        ),
        when_to_use=[
            "You have a name (and company) but need email/phone/LinkedIn",
            "Enriching a lead record before outreach",
        ],
        when_not_to_use=[
            "No prospect database is connected",
            "You already have complete contact details",
        ],
        returns="Dict with person_id, name, title, company, email, phone, linkedin_url, company_size, industry, location.",
        parameters={
            "type": "object",
            "properties": {
                **_ENRICH_PROSPECT_PARAMS["properties"],
                **_PROVIDER_PARAM,
            },
        },
    ),
    "create_crm_contact": ToolSpec(
        name="create_crm_contact",
        category="integrations",
        description="Create a contact or lead in the connected CRM (e.g. Zoho).",
        when_to_use=[
            "The user asks to save a lead/contact to the CRM",
            "A qualified lead should be recorded outside Rio",
        ],
        when_not_to_use=[
            "No CRM is connected (Zoho)",
        ],
        returns="The created CRM record id and any response fields.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "phone": {"type": "string"},
                "company": {"type": "string"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                **_PROVIDER_PARAM,
            },
            "required": ["name"],
        },
    ),
    "update_crm_contact": ToolSpec(
        name="update_crm_contact",
        category="integrations",
        description="Update an existing contact/lead in the connected CRM (e.g. Zoho) by record id.",
        when_to_use=["The user asks to change CRM fields for an existing record"],
        when_not_to_use=["No CRM is connected", "A brand-new contact should be created — use create_crm_contact"],
        returns="Updated record confirmation and response fields.",
        parameters={
            "type": "object",
            "properties": {
                "record_id": {"type": "string"},
                "data": {"type": "object", "description": "Field map of values to update."},
                **_PROVIDER_PARAM,
            },
            "required": ["record_id", "data"],
        },
    ),
    "crm_query": ToolSpec(
        name="crm_query",
        category="integrations",
        description="Query records in the connected CRM (e.g. Zoho) using a query string or module.",
        when_to_use=[
            "The user asks for CRM records matching criteria (deals, contacts, leads)",
        ],
        when_not_to_use=["No CRM is connected"],
        returns="Matching CRM records.",
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "module": {"type": "string", "description": "CRM module/object, e.g. Contacts (Zoho) or contacts/companies/deals (HubSpot)."},
                **_PROVIDER_PARAM,
            },
        },
    ),
    "enroll_sequence": ToolSpec(
        name="enroll_sequence",
        category="integrations",
        description="Enroll a contact into an outreach sequence in the connected engagement platform (Apollo).",
        when_to_use=["The user asks to add a contact to an outreach/email sequence"],
        when_not_to_use=["Apollo is not connected"],
        returns="Enrollment confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "contact_id": {"type": "string"},
                "sequence_id": {"type": "string"},
            },
            "required": ["contact_id", "sequence_id"],
        },
    ),
    "outreach_analytics": ToolSpec(
        name="outreach_analytics",
        category="integrations",
        description="Pull analytics or reports from the connected outreach platform (Apollo).",
        when_to_use=["The user asks about outreach performance or campaign analytics"],
        when_not_to_use=["Apollo is not connected"],
        returns="Analytics report data.",
        parameters={
            "type": "object",
            "properties": {
                "report_name": {"type": "string"},
            },
        },
    ),
    "inventory_lookup": ToolSpec(
        name="inventory_lookup",
        category="integrations",
        description="Look up a product's stock and details across connected inventory sources by SKU.",
        when_to_use=[
            "The user asks if a product is in stock or its price/details",
        ],
        when_not_to_use=["No inventory source is connected"],
        returns="Product record with stock, price, and details, or a not-found response.",
        parameters={
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["sku"],
        },
    ),
    "inventory_reserve": ToolSpec(
        name="inventory_reserve",
        category="integrations",
        description="Reserve quantity of a product by SKU across connected inventory sources.",
        when_to_use=["The user confirms an order/demo needs stock set aside"],
        when_not_to_use=["No inventory source is connected"],
        returns="Reservation confirmation with the reserved quantity.",
        parameters={
            "type": "object",
            "properties": {
                "sku": {"type": "string"},
                "qty": {"type": "integer"},
            },
            "required": ["sku", "qty"],
        },
    ),
    "schedule_meeting": ToolSpec(
        name="schedule_meeting",
        category="integrations",
        description=(
            "Schedule a meeting or demo on the connected scheduling app "
            "(Cal.com or Calendly)."
        ),
        when_to_use=[
            "The user agrees to book a meeting or demo and provides a time",
        ],
        when_not_to_use=[
            "No scheduling app is connected",
            "The user only wants availability — use get_availability first",
        ],
        returns="Booking confirmation with meeting details/link.",
        parameters=_SCHEDULING_PARAMS,
    ),
    "get_availability": ToolSpec(
        name="get_availability",
        category="integrations",
        description="Check available slots on the connected scheduling app for a given date.",
        when_to_use=["The user asks what times are available for a meeting/demo"],
        when_not_to_use=["No scheduling app is connected"],
        returns="List of available slots.",
        parameters={
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date, YYYY-MM-DD."},
                "event_type_id": {"type": "string"},
            },
            "required": ["date"],
        },
    ),
    "list_bookings": ToolSpec(
        name="list_bookings",
        category="integrations",
        description="List existing bookings/events from the connected scheduling app.",
        when_to_use=["The user asks about their upcoming meetings or bookings"],
        when_not_to_use=["No scheduling app is connected"],
        returns="List of bookings with status and times.",
        parameters={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "from_date": {"type": "string"},
                "to_date": {"type": "string"},
            },
        },
    ),
    "reschedule_meeting": ToolSpec(
        name="reschedule_meeting",
        category="integrations",
        description="Reschedule an existing booking on the connected scheduling app (Cal.com, Calendly, or Microsoft 365 calendar).",
        when_to_use=["The user asks to move an existing meeting to a new time"],
        when_not_to_use=["No scheduling app is connected"],
        returns="Updated booking confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "booking_id": {"type": "string"},
                "new_start_time": {"type": "string"},
                "end_time": {"type": "string", "description": "ISO 8601 new end datetime (optional; Microsoft 365 calendar)."},
                "subject": {"type": "string", "description": "New subject (optional; Microsoft 365 calendar)."},
                **_PROVIDER_PARAM,
            },
            "required": ["booking_id", "new_start_time"],
        },
    ),
    "cancel_meeting": ToolSpec(
        name="cancel_meeting",
        category="integrations",
        description="Cancel an existing booking on the connected scheduling app.",
        when_to_use=["The user asks to cancel a scheduled meeting"],
        when_not_to_use=["No scheduling app is connected"],
        returns="Cancellation confirmation.",
        parameters={
            "type": "object",
            "properties": {
                "booking_id": {"type": "string"},
                "reason": {"type": "string"},
                **_PROVIDER_PARAM,
            },
            "required": ["booking_id"],
        },
    ),
    "create_meeting": ToolSpec(
        name="create_meeting",
        category="integrations",
        description=(
            "Create a Zoom meeting via the Zoom REST API and return a join URL. "
            "This is the auto-fallback meeting-link provider used when the company "
            "has Zoom connected but not Google Calendar — the booking flow prefers "
            "Google Meet, then falls back to a Zoom link."
        ),
        when_to_use=[
            "A booking needs an online meeting link and Google Calendar is not connected",
            "The user explicitly asks for a Zoom meeting link",
        ],
        when_not_to_use=[
            "Google Calendar is connected — book_meeting/book_demo prefer a Google Meet link",
            "Zoom is not connected, or the app lacks the meeting:write scope",
        ],
        returns="Dict with meeting_id, join_url, start_url, start_time, provider='zoom'.",
        parameters={
            "type": "object",
            "properties": {
                "topic": {"type": "string"},
                "start_time": {"type": "string", "description": "ISO 8601 start datetime."},
                "duration_minutes": {"type": "integer", "default": 30},
                "attendee_email": {"type": "string"},
            },
            "required": ["topic"],
        },
    ),
    "send_microsoft_email": ToolSpec(
        name="send_microsoft_email",
        category="integrations",
        description=(
            "Send an email from the company's connected Microsoft 365 mailbox "
            "(Outlook) using Microsoft Graph. Use when the user wants an email "
            "sent from their Microsoft account — e.g. sending the quote, meeting "
            "notes, or follow-up from Outlook."
        ),
        when_to_use=[
            "The user asks to send an email from Outlook / Microsoft 365",
            "A document or quote should be emailed from the connected mailbox",
        ],
        when_not_to_use=[
            "Microsoft 365 is not connected",
            "A WhatsApp message is preferred — use send_communication instead",
        ],
        returns="Confirmation with recipient and subject on success.",
        parameters={
            "type": "object",
            "properties": {
                "to_email": {"type": "string"},
                "subject": {"type": "string"},
                "body": {"type": "string"},
                "cc_email": {"type": "string"},
            },
            "required": ["to_email", "subject"],
        },
    ),
}


def all_capability_specs() -> list[ToolSpec]:
    """Return the specs for all capability tools, in a stable order."""
    return [_CAPABILITY_SPECS[name] for name in _CAPABILITY_SPECS]
