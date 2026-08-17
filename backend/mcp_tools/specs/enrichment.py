from mcp_tools.spec import ToolSpec

score_lead = ToolSpec(
    name="score_lead",
    category="enrichment",
    description=(
        "ML-powered lead scoring using TabPFN trained on your company's own won/lost data. "
        "Returns a 0–100 score and the top contributing factors. "
        "Falls back to a heuristic baseline (seniority, enrichment, engagement, deal size) "
        "when insufficient training data exists."
    ),
    when_to_use=[
        "Deciding which leads to prioritize for the next calling session",
        "About to reach out to a cold lead and want to know if it's worth the time",
        "Building a ranked call list for a campaign",
    ],
    when_not_to_use=[
        "Lead has no CRM data yet — scoring will be unreliable",
        "You already know this lead is hot (verbal confirmation of intent)",
    ],
    returns=(
        "Dict: {lead_id, score: float(0-100), tier: 'hot'|'warm'|'cold', "
        "factors: [{name, impact: 'positive'|'negative', weight}], model: 'ml'|'heuristic'}."
    ),
)

recommend_channel = ToolSpec(
    name="recommend_channel",
    category="enrichment",
    description=(
        "ML-powered channel recommendation: which of call/email/WhatsApp is most likely "
        "to get a response from this specific lead right now. Uses TabPFN trained on your "
        "engagement history, with heuristic fallback by pipeline stage."
    ),
    when_to_use=[
        "About to reach out to a lead and unsure whether to call, email, or WhatsApp",
        "Planning a follow-up cadence and want the optimal channel mix",
        "Campaign sequencing — select channel per lead rather than blasting all",
    ],
    when_not_to_use=[
        "Lead has explicitly opted out of a channel — respect that regardless of score",
        "Lead's preferred channel is already known from conversation",
    ],
    returns=(
        "Dict: {lead_id, recommended_channel: 'call'|'email'|'whatsapp', "
        "confidence: float, reasoning: str, model: 'ml'|'heuristic'}."
    ),
)

check_opt_out = ToolSpec(
    name="check_opt_out",
    category="enrichment",
    description=(
        "Check whether a lead has opted out of a specific outreach channel (call, email, WhatsApp). "
        "Always call this before sending any outreach to avoid compliance violations."
    ),
    when_to_use=[
        "Before sending an email, WhatsApp, or making a call to any lead",
        "Compliance check before launching a campaign or bulk outreach",
        "Lead mentions they don't want to be contacted — verify current opt-out status",
    ],
    when_not_to_use=[
        "You've already confirmed opt-out status in this call session",
    ],
    returns=(
        "Dict: {lead_id, channel, opted_out: bool, opted_out_at: datetime|None, reason: str|None}."
    ),
)
