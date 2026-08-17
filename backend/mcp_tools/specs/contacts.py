from mcp_tools.spec import ToolSpec

create_contact = ToolSpec(
    name="create_contact",
    category="contacts",
    description=(
        "Create a new contact record linked to a lead — used for decision makers, "
        "influencers, and buying committee members who aren't the primary lead. "
        "One lead can have multiple contacts."
    ),
    when_to_use=[
        "Lead mentions a colleague who is also a decision maker",
        "Prospect has a procurement manager or finance head who needs to approve",
        "B2B sale with a buying committee — capture all stakeholders",
    ],
    when_not_to_use=[
        "Contact IS the primary lead — update the lead record instead",
        "You don't have a lead_id yet",
    ],
    returns="Dict: {contact_id, name, email, phone, role, lead_id, created_at}.",
)

list_contacts = ToolSpec(
    name="list_contacts",
    category="contacts",
    description=(
        "List all contacts associated with a lead. Use before a call to know "
        "who the stakeholders are, or to check if a decision maker has already been captured."
    ),
    when_to_use=[
        "Preparing for a call — review who the known stakeholders are",
        "Lead says 'let me loop in my manager' — check if that person is already in CRM",
    ],
    when_not_to_use=[
        "No lead_id available",
        "This is a B2C lead with a single buyer",
    ],
    returns=(
        "List of dicts: [{contact_id, name, email, phone, role, is_active}]. "
        "Empty list if no contacts recorded."
    ),
)
