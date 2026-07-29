from mcp_tools.spec import ToolSpec

get_lead_requirements = ToolSpec(
    name="get_lead_requirements",
    category="post_call",
    description=(
        "Retrieve the structured requirements captured for a lead: use case, budget range, "
        "timeline, decision makers, pain points, competitors mentioned, and products of interest. "
        "Use this before a call to brief the agent, or after a call to verify what was captured."
    ),
    when_to_use=[
        "Starting a follow-up call and need to recall what the lead discussed previously",
        "Preparing a quote and need confirmed budget/product requirements",
        "Verifying that requirements captured during a prior call are complete",
    ],
    when_not_to_use=[
        "No prior call has occurred with this lead — requirements will be empty",
        "You need the lead's contact details — use get_lead_info instead",
    ],
    returns=(
        "Dict: {lead_id, use_case, budget_range, timeline, decision_makers, "
        "pain_points, competitors, required_products, updated_at}. "
        "None if no requirements have been captured yet."
    ),
)

upsert_lead_requirements = ToolSpec(
    name="upsert_lead_requirements",
    category="post_call",
    description=(
        "Save or update structured requirements gathered during a call: use case, budget, timeline, "
        "decision makers, pain points, competitor mentions, and desired products. "
        "Call this at the end of every qualifying call to persist what you learned."
    ),
    when_to_use=[
        "End of a qualifying call — save everything learned about the lead's needs",
        "Lead provides updated budget, timeline, or product requirements",
        "New decision maker or competitor is mentioned",
    ],
    when_not_to_use=[
        "You don't have a lead_id yet — call get_or_create_lead first",
        "Nothing new was learned — skip to avoid overwriting good data",
    ],
    returns="Dict: {lead_id, requirements_id, updated_at, fields_updated: list}.",
)

send_csat = ToolSpec(
    name="send_csat",
    category="post_call",
    description=(
        "Send a CSAT (customer satisfaction) survey to a lead after a completed call or interaction. "
        "Creates a tokenized survey link and sends via the lead's preferred channel. "
        "Deduplicates — won't send a second survey within the configurable cooldown window."
    ),
    when_to_use=[
        "Call has ended and the lead was cooperative / engaged",
        "Service ticket has been resolved and you want feedback",
        "Post-demo follow-up to capture product impression",
    ],
    when_not_to_use=[
        "Lead was hostile, hung up, or opted out",
        "A CSAT was already sent to this lead in the last 24 hours",
        "Interaction was a voicemail or failed call",
    ],
    returns="Dict: {csat_id, channel_sent, survey_url, expires_at, is_duplicate: bool}.",
)

create_ticket = ToolSpec(
    name="create_ticket",
    category="post_call",
    description=(
        "Open a service ticket for a lead's post-sale issue, complaint, or installation request. "
        "Assigns priority, sets SLA, and optionally assigns to a team member. "
        "Use this when a customer calls with a complaint or service request that can't be resolved immediately."
    ),
    when_to_use=[
        "Customer reports a product defect, delivery issue, or technical problem",
        "Call reveals an installation request that needs to be scheduled",
        "Escalation required — issue can't be resolved on the current call",
    ],
    when_not_to_use=[
        "Issue can be resolved immediately on the call — no ticket needed",
        "This is a sales inquiry, not a service/support issue",
    ],
    returns="Dict: {ticket_id, ticket_number, status, priority, sla_due_at, assignee}.",
)

list_tickets = ToolSpec(
    name="list_tickets",
    category="post_call",
    description=(
        "List open service tickets for a lead. Use this at the start of a call "
        "to brief the agent on any outstanding issues the customer has reported."
    ),
    when_to_use=[
        "Customer calls in and you want to check if they have open service requests",
        "Follow-up call where you need to reference a previous complaint",
    ],
    when_not_to_use=[
        "No lead_id is available",
        "Customer is a first-time caller with no history",
    ],
    returns=(
        "List of dicts: [{ticket_id, ticket_number, title, status, priority, created_at, sla_due_at}]. "
        "Empty list if no open tickets."
    ),
)

set_next_action = ToolSpec(
    name="set_next_action",
    category="post_call",
    description=(
        "Set the next scheduled action for a lead after a call: follow-up call, send quote, "
        "send proposal, book demo, or close lost. Updates the lead's next_action and next_action_due_at fields."
    ),
    when_to_use=[
        "End of every call — always set a clear next action",
        "Lead says 'call me back Thursday' — schedule a follow-up",
        "Lead requested a quote — set 'send_quote' with due date",
    ],
    when_not_to_use=[
        "Lead is already won or lost — no next action needed",
        "You don't have a lead_id",
    ],
    returns="Dict: {lead_id, next_action, next_action_due_at, updated_at}.",
)
