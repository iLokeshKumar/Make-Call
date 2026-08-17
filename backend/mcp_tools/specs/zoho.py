from mcp_tools.spec import ToolSpec

zoho_get_pipeline = ToolSpec(
    name="zoho_get_pipeline",
    category="zoho",
    description=(
        "Fetch open deals from the connected Zoho CRM account. Returns deal name, "
        "stage, amount, account, and closing date for the most recent open deals. "
        "Use this for pipeline review, deal prioritization, or syncing CRM state."
    ),
    when_to_use=[
        "Manager asks about the Zoho CRM pipeline or open deals",
        "You want to sync or cross-reference deals between Rio and Zoho CRM",
        "Checking deal stages or amounts in Zoho before a call",
    ],
    when_not_to_use=[
        "Zoho CRM has not been connected — check status first",
        "You only need Rio's internal pipeline — use get_pipeline_funnel instead",
    ],
    returns=(
        "List of dicts: [{deal_id, deal_name, stage, amount, account_name, closing_date}]. "
        "Empty list if no open deals found."
    ),
)

zoho_create_deal = ToolSpec(
    name="zoho_create_deal",
    category="zoho",
    description=(
        "Create a new deal record in the connected Zoho CRM account. "
        "Pushes a qualified Rio lead into Zoho as a Deal with stage, amount, "
        "and account name. Use this to keep Zoho CRM in sync after lead qualification."
    ),
    when_to_use=[
        "Lead has been qualified in Rio and needs to be pushed to Zoho CRM",
        "Manager wants all qualified leads visible in Zoho",
        "Deal is ready to be tracked in Zoho's sales pipeline",
    ],
    when_not_to_use=[
        "Zoho CRM is not connected",
        "Lead is not yet qualified — don't create premature deals",
    ],
    returns="Dict: {deal_id, deal_name, stage, zoho_record_url}.",
)

zoho_update_contact = ToolSpec(
    name="zoho_update_contact",
    category="zoho",
    description=(
        "Update an existing contact record in Zoho CRM by Zoho contact ID. "
        "Can update phone, email, title, and custom fields. "
        "Use this to keep Zoho contact details in sync after a call."
    ),
    when_to_use=[
        "Lead gave updated contact information during a call",
        "You have a Zoho contact_id and need to patch their details",
        "Syncing enriched data back to Zoho after Apollo enrichment",
    ],
    when_not_to_use=[
        "You don't have the Zoho contact_id — search for the contact first",
        "Zoho CRM is not connected",
    ],
    returns="Dict: {contact_id, updated_fields, zoho_record_url}.",
)
