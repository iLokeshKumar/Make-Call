from mcp_tools.spec import ToolSpec

get_product_info = ToolSpec(
    name="get_product_info",
    category="inventory",
    description=(
        "Retrieve real-time product details from the CRM inventory including price, "
        "stock count, SKU, description, and category. Use this before quoting or when "
        "a customer asks about availability, pricing, or specifications."
    ),
    when_to_use=[
        "Customer asks 'how much does X cost?' or 'is X in stock?'",
        "You are about to build a quote and need the current price",
        "Customer asks about product features, warranty, or specifications",
        "You need the SKU to reference a product in a quote",
    ],
    when_not_to_use=[
        "You already retrieved this product's info earlier in the call",
        "Customer is asking about an order they already placed — check interaction history instead",
    ],
    returns=(
        "Dict: {id, name, sku, description, price, stock_count, category, is_active}. "
        "Empty dict if product not found — do NOT assume the product exists."
    ),
)

create_quote_for_lead = ToolSpec(
    name="create_quote_for_lead",
    category="inventory",
    description=(
        "Generate a formal quote for a lead with one or more product line items. "
        "Calculates line totals, applies discounts, and creates the quote record. "
        "Optionally sends the quote PDF to the lead's email."
    ),
    when_to_use=[
        "Lead explicitly asks for a quote or proposal",
        "You have confirmed product, quantity, and the lead wants a formal document",
        "Lead says 'send me the pricing' or 'what would it cost for N units?'",
    ],
    when_not_to_use=[
        "Lead has not confirmed interest — quote only after verbal buy-in",
        "You don't have a lead_id yet — call get_or_create_lead first",
        "Lead is just browsing — use get_product_info to share pricing verbally first",
    ],
    returns=(
        "Dict: {quote_id, quote_number, total_amount, line_items, pdf_url, status}. "
        "On failure: error string."
    ),
)

sync_product_catalog = ToolSpec(
    name="sync_product_catalog",
    category="inventory",
    description=(
        "Trigger a full sync of the product catalog from the connected inventory source "
        "(e.g. Zoho Books, Tally, CSV upload). Fetches updated prices and stock levels. "
        "This is an admin/background operation, not a customer-facing tool."
    ),
    when_to_use=[
        "Admin requests a manual catalog refresh",
        "Prices seem out of date and need to be pulled from the source system",
    ],
    when_not_to_use=[
        "During a live customer call — this is a background operation",
        "No inventory source has been configured for the company",
    ],
    returns="Dict: {synced_count: int, errors: list[str], duration_ms: int}.",
)
