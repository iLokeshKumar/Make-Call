from mcp_tools.spec import ToolSpec

get_or_create_lead = ToolSpec(
    name="get_or_create_lead",
    category="crm",
    description=(
        "Look up a lead by phone number or email. If not found, create a new lead record "
        "with the provided contact details. Returns the lead's full profile including "
        "status, owner, tags, and last interaction summary."
    ),
    when_to_use=[
        "Call begins and you need to identify who you're speaking with",
        "Lead provides their phone/email and you need to pull their CRM profile",
        "You want to ensure a record exists before logging an interaction",
    ],
    when_not_to_use=[
        "You already have the lead_id from earlier in the call",
        "This is a known internal user, not a prospect",
    ],
    returns=(
        "Dict: {lead_id, name, phone, email, status, owner, tags, company_name, "
        "last_interaction_at, created: bool}. created=True means a new record was made."
    ),
)

get_lead_info = ToolSpec(
    name="get_lead_info",
    category="crm",
    description=(
        "Retrieve full profile for a known lead by ID: contact details, pipeline status, "
        "assigned owner, tags, requirements, and a summary of recent interactions."
    ),
    when_to_use=[
        "You have a lead_id and need their current details",
        "Checking if a lead has open quotes or pending follow-ups",
        "Reviewing lead history before a follow-up call",
    ],
    when_not_to_use=[
        "You don't have a lead_id yet — use get_or_create_lead first",
    ],
    returns=(
        "Dict: {lead_id, name, phone, email, status, owner, tags, requirements, "
        "recent_interactions: list, open_quotes: list}."
    ),
)

get_lead_context = ToolSpec(
    name="get_lead_context",
    category="crm",
    description=(
        "Retrieve the lead's CRM context in one call: profile, effective timezone, "
        "recent interactions, requirement snapshot, and scheduled appointments."
    ),
    when_to_use=[
        "You need the lead's effective timezone before booking or explaining a time",
        "You need one tenant-scoped database payload instead of stitching together multiple reads",
        "You are debugging why interactions, appointments, and emails disagree",
    ],
    when_not_to_use=[
        "You only need a basic lead profile with no history",
        "You are trying to run arbitrary SQL against the database",
    ],
    returns=(
        "Dict: {lead, effective_timezone, timezone_source, recent_interactions, "
        "requirement, appointments}."
    ),
)

update_lead_status = ToolSpec(
    name="update_lead_status",
    category="crm",
    description=(
        "Update the pipeline status of a lead (e.g. new → qualified → proposal → won/lost). "
        "Optionally add a note explaining the status change."
    ),
    when_to_use=[
        "Call outcome is clear and you want to move the lead forward in the pipeline",
        "Lead confirmed they want a proposal — move to 'proposal'",
        "Lead said they're not interested — mark as 'lost' with a reason",
        "Lead converted — mark as 'won'",
    ],
    when_not_to_use=[
        "Outcome is unclear — don't update until you have a definitive signal",
        "You don't have a lead_id",
    ],
    returns="Dict: {lead_id, old_status, new_status, updated_at}.",
)
