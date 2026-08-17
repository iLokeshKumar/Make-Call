from mcp_tools.spec import ToolSpec

get_pipeline_funnel = ToolSpec(
    name="get_pipeline_funnel",
    category="analytics",
    description=(
        "Return a breakdown of the company's lead pipeline by status — "
        "how many leads are in each stage and what percentage of the total they represent. "
        "Use this to give a sales summary or assess pipeline health."
    ),
    when_to_use=[
        "Manager asks 'how is the pipeline looking?'",
        "You need a high-level funnel overview (new → qualified → proposal → won/lost)",
        "Dashboard or reporting context where stage distribution is needed",
    ],
    when_not_to_use=[
        "Caller wants details about a specific lead — use get_lead_info instead",
        "Caller wants engagement metrics (calls made, emails sent) — use get_engagement_summary",
    ],
    returns=(
        "List of dicts: [{status: str, count: int, percent: float}] sorted by count descending. "
        "Empty list if no leads exist."
    ),
)

get_engagement_summary = ToolSpec(
    name="get_engagement_summary",
    category="analytics",
    description=(
        "Return engagement activity metrics for the last N days: calls made, emails sent, "
        "WhatsApp messages, total touchpoints, and campaign performance. "
        "Optionally scoped to a single sales rep."
    ),
    when_to_use=[
        "Manager asks 'how many calls did we make this week?'",
        "You need to report on outreach activity (emails, calls, WhatsApp)",
        "Rep wants to know their own activity metrics",
        "Dashboard showing recent engagement trend",
    ],
    when_not_to_use=[
        "You need pipeline stage data — use get_pipeline_funnel instead",
        "You need a specific lead's timeline — use get_lead_info instead",
    ],
    returns=(
        "Dict: {calls: int, emails: int, whatsapp: int, total_touchpoints: int, "
        "lookback_days: int, top_campaigns: list}."
    ),
)
