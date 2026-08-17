from mcp_tools.spec import ToolSpec

apollo_search_leads = ToolSpec(
    name="apollo_search_leads",
    category="apollo",
    description=(
        "Search Apollo.io's database of 275M+ people to find leads matching an ICP. "
        "Filter by job title, industry, company size, location, and seniority. "
        "Returns contact name, title, company, LinkedIn URL, and estimated email."
    ),
    when_to_use=[
        "Sales rep wants to find new prospects matching a target profile",
        "Campaign needs a fresh lead list before outreach",
        "Building a call list for a specific industry or geography",
    ],
    when_not_to_use=[
        "Apollo is not connected — call get_apollo_auth_url first",
        "Looking up a specific known person — use apollo_enrich_contact instead",
        "Daily search limit has been reached",
    ],
    returns=(
        "List of dicts: [{person_id, name, title, company, location, "
        "linkedin_url, email (if available), phone (if available)}]. "
        "Up to `limit` results (default 10)."
    ),
)

apollo_enrich_contact = ToolSpec(
    name="apollo_enrich_contact",
    category="apollo",
    description=(
        "Enrich a known contact with Apollo data: find their verified email, "
        "LinkedIn URL, job title, company size, and social profiles. "
        "Matches by email or name+company combination."
    ),
    when_to_use=[
        "You have a lead's name and company but need their email or phone",
        "Enriching a Rio lead before the call with their LinkedIn and title",
        "Verifying contact details before sending outreach",
    ],
    when_not_to_use=[
        "Apollo is not connected",
        "You already have complete contact details",
        "You need a bulk list of new leads — use apollo_search_leads instead",
    ],
    returns=(
        "Dict: {person_id, name, title, company, email, phone, linkedin_url, "
        "company_size, industry, location}. "
        "Returns partial data if only some fields are available."
    ),
)
