from mcp_tools.spec import ToolSpec

search_knowledge_base = ToolSpec(
    name="search_knowledge_base",
    category="knowledge",
    description=(
        "Semantic search over the company's knowledge base using natural language. "
        "Covers product docs, objection rebuttals, playbooks, competitor intel, pricing, "
        "and policy documents. Returns ranked text chunks relevant to the query."
    ),
    when_to_use=[
        "Customer asks a question you don't have in memory (price, feature, policy)",
        "You need a specific rebuttal or talking point",
        "Customer mentions a competitor and you need a counter-script",
        "You need to verify a spec or warranty detail before quoting",
    ],
    when_not_to_use=[
        "You already know the answer from earlier in the call",
        "The customer is asking about their specific order status — use get_lead_info instead",
        "You need real-time stock levels — use get_product_info instead",
    ],
    returns=(
        "List of dicts: {content: str, collection: str, metadata: {title, tags}, score: float, source: str}. "
        "Empty list if no results found."
    ),
)

get_objection_rebuttal = ToolSpec(
    name="get_objection_rebuttal",
    category="knowledge",
    description=(
        "Fetch the top company-trained objection rebuttals sorted by how frequently that "
        "objection appears in past calls. Use this to handle 'too expensive', "
        "'already have a solution', 'need to think about it', and similar blockers."
    ),
    when_to_use=[
        "Prospect pushes back with a price, timing, or need objection",
        "You need a ready-made, company-approved response to a common objection",
        "Prospect mentions a competitor as a reason not to buy",
    ],
    when_not_to_use=[
        "You have already used this tool in the current turn — avoid repeating",
        "The objection is highly specific and personal — handle conversationally instead",
    ],
    returns=(
        "Formatted string of objections and rebuttals ready to inject into your response. "
        "Empty string if no rebuttals have been configured for this company."
    ),
)

get_competitor_intel = ToolSpec(
    name="get_competitor_intel",
    category="knowledge",
    description=(
        "Search the knowledge base specifically for competitor intelligence: counter-scripts, "
        "differentiation points, known weaknesses, and pricing comparisons. "
        "Scoped to the 'competitors' collection for precision."
    ),
    when_to_use=[
        "Prospect explicitly names a competitor (Salesforce, HubSpot, Zoho, etc.)",
        "Prospect says 'we already use X' or 'X is cheaper'",
        "You want to proactively differentiate against a likely competitor",
    ],
    when_not_to_use=[
        "No competitor has been mentioned — don't bring up competitors unprompted",
        "Query is about our own product features — use search_knowledge_base instead",
    ],
    returns=(
        "List of ranked text chunks from the competitors collection. "
        "Each chunk contains counter-messaging or differentiation notes."
    ),
)
