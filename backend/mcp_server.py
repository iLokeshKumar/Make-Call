from __future__ import annotations

import asyncio
import logging
from typing import Any

try:
    from fastmcp import FastMCP
    _FASTMCP_AVAILABLE = True
except ImportError:
    FastMCP = None
    _FASTMCP_AVAILABLE = False

from sqlmodel import Session, select

from database import engine, rls_company_id
from models.models import Appointment, Interaction, Lead, Product, User
from services.agent.agent_tool_service import (
    book_demo as service_book_demo,
    book_meeting as service_book_meeting,
    check_guardrails as service_check_guardrails,
    check_icp_qualification as service_check_icp_qualification,
    get_call_latency_summary as service_get_call_latency_summary,
    get_google_auth_url as service_get_google_auth_url,
    get_or_create_lead as service_get_or_create_lead,
    get_product_info as service_get_product_info,
    send_communication as service_send_communication,
    submit_google_auth_code as service_submit_google_auth_code,
    sync_product_catalog as service_sync_product_catalog,
)

logger = logging.getLogger(__name__)

if _FASTMCP_AVAILABLE:
    mcp = FastMCP("Rio CRM Navigator")
else:
    mcp = None  # type: ignore[assignment]


# ─── helpers ──────────────────────────────────────────────────────────────────

def _resolve_user_context(session: Session, user_id: int | None) -> tuple[int | None, int | None]:
    if not user_id:
        return None, None
    user = session.get(User, user_id)
    if not user:
        return None, None
    return user.company_id, user.id


async def _run(user_id: int | None, fn) -> Any:
    """
    Resolve user → company_id, set RLS context, run fn(session, company_id, actor_user_id)
    inside asyncio.to_thread so the event loop is never blocked.
    Returns fn's result, or {"error": "..."} on failure.
    """
    def _sync():
        with Session(engine) as session:
            company_id, actor_user_id = _resolve_user_context(session, user_id)
            if not company_id:
                return {"error": "User context not found"}
            token = rls_company_id.set(company_id)
            try:
                return fn(session, company_id, actor_user_id)
            finally:
                rls_company_id.reset(token)
    return await asyncio.to_thread(_sync)


# ─── resources ────────────────────────────────────────────────────────────────

@mcp.resource("crm://leads/{user_id}")
async def get_leads_summary(user_id: int) -> list[dict[str, Any]]:
    """
    List the 100 most recent leads for this company.

    Returns: id, name, normalized_phone, status, qualification_status, next_action.
    Use this to give an AI agent a bird's-eye view of the pipeline before
    selecting which leads to work today.
    """
    def _q(session, company_id, _actor):
        leads = session.exec(
            select(Lead)
            .where(Lead.company_id == company_id)
            .order_by(Lead.created_at.desc())
        ).all()
        return [
            {
                "id": lead.id,
                "name": lead.name,
                "normalized_phone": lead.normalized_phone,
                "status": lead.status,
                "qualification_status": lead.qualification_status,
                "next_action": lead.next_action,
            }
            for lead in leads[:100]
        ]
    return await _run(user_id, _q)


@mcp.resource("crm://inventory/{user_id}")
async def get_inventory(user_id: int) -> list[dict[str, Any]]:
    """
    Return the company's product catalog (up to 100 products).

    Returns: id, name, sku, stock, price, currency, note.
    Use this to give the agent product context before a sales call.
    """
    def _q(session, company_id, _actor):
        products = session.exec(
            select(Product)
            .where(Product.company_id == company_id)
            .order_by(Product.created_at.desc())
        ).all()
        return [
            {
                "id": product.id,
                "name": product.name,
                "sku": product.sku,
                "stock": product.stock,
                "price": str(product.price),
                "currency": product.currency,
                "note": product.note,
            }
            for product in products[:100]
        ]
    return await _run(user_id, _q)


@mcp.resource("crm://interactions/{user_id}/{lead_id}")
async def get_lead_interactions(user_id: int, lead_id: int) -> list[dict[str, Any]]:
    """
    Return the 50 most recent interactions for a specific lead.

    Returns: id, type, channel, direction, content, status, started_at.
    Use before a call to brief the agent on all prior touchpoints.
    """
    def _q(session, company_id, _actor):
        interactions = session.exec(
            select(Interaction)
            .where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead_id,
            )
            .order_by(Interaction.started_at.desc())
        ).all()
        return [
            {
                "id": item.id,
                "type": item.type,
                "channel": item.channel,
                "direction": item.direction,
                "content": item.content,
                "status": item.status,
                "started_at": item.started_at.isoformat() if item.started_at else None,
            }
            for item in interactions[:50]
        ]
    return await _run(user_id, _q)


@mcp.resource("crm://appointments/{user_id}")
async def get_appointments(user_id: int) -> list[dict[str, Any]]:
    """
    Return the 100 most recent appointments for this company.

    Returns: id, lead_id, appointment_time, status, meeting_link.
    Use to show upcoming scheduled demos and follow-ups.
    """
    def _q(session, company_id, _actor):
        appointments = session.exec(
            select(Appointment)
            .where(Appointment.company_id == company_id)
            .order_by(Appointment.appointment_time.desc())
        ).all()
        return [
            {
                "id": item.id,
                "lead_id": item.lead_id,
                "appointment_time": item.appointment_time.isoformat(),
                "status": item.status,
                "meeting_link": item.meeting_link,
            }
            for item in appointments[:100]
        ]
    return await _run(user_id, _q)


@mcp.resource("crm://knowledge/{user_id}/{collection}")
async def get_knowledge_collection(user_id: int, collection: str) -> list[dict[str, Any]]:
    """
    List knowledge base documents in a collection for this company.

    Valid collections: products, objections, competitors, playbooks,
    coaching, sops, transcripts, or 'all' for every collection.

    Returns: id, collection, title, tags, last_indexed_at.
    """
    def _q(session, company_id, _actor):
        from models.models import KnowledgeDocument
        q = select(KnowledgeDocument).where(
            KnowledgeDocument.company_id == company_id,
            KnowledgeDocument.is_active == True,  # noqa: E712
        )
        if collection != "all":
            q = q.where(KnowledgeDocument.collection == collection)
        docs = session.exec(q.limit(200)).all()
        return [
            {
                "id": d.id,
                "collection": d.collection,
                "title": d.title,
                "tags": d.tags,
                "last_indexed_at": str(d.last_indexed_at),
            }
            for d in docs
        ]
    return await _run(user_id, _q)


@mcp.resource("crm://pipeline/{user_id}")
async def get_pipeline(user_id: int) -> dict[str, Any]:
    """
    Return lead counts grouped by ISM stage (funnel view).

    Returns: {stage_name: count} dict.
    Use to give the agent a quick funnel health-check before a coaching session.
    """
    from sqlalchemy import func

    def _q(session, company_id, _actor):
        rows = session.exec(
            select(Lead.ism_stage, func.count(Lead.id).label("count"))
            .where(Lead.company_id == company_id)
            .group_by(Lead.ism_stage)
        ).all()
        return {r[0] or "unknown": r[1] for r in rows}

    return await _run(user_id, _q)


@mcp.resource("crm://analytics/{user_id}")
async def get_analytics_summary(user_id: int) -> dict[str, Any]:
    """
    Return a 30-day engagement summary (calls, emails, opens, replies).

    Returns an analytics dict from analytics_service.get_engagement_summary.
    Use for daily performance briefings.
    """
    def _q(session, company_id, _actor):
        try:
            from services.analytics.analytics_service import get_engagement_summary
            return get_engagement_summary(session=session, company_id=company_id, days=30)
        except Exception as exc:
            return {"error": str(exc)}

    return await _run(user_id, _q)


@mcp.resource("crm://quotes/{user_id}/{lead_id}")
async def get_lead_quotes(user_id: int, lead_id: int) -> list[dict[str, Any]]:
    """
    Return all quotes for a lead, newest first.

    Returns: id, status, valid_days, notes, created_at, items[].
    """
    def _q(session, company_id, _actor):
        from models.models import Quote, QuoteItem
        quotes = session.exec(
            select(Quote)
            .where(Quote.company_id == company_id, Quote.lead_id == lead_id)
            .order_by(Quote.created_at.desc())
        ).all()
        result = []
        for q in quotes:
            items = session.exec(select(QuoteItem).where(QuoteItem.quote_id == q.id)).all()
            result.append({
                "id": q.id,
                "status": q.status,
                "valid_days": q.valid_days,
                "notes": q.notes,
                "created_at": str(q.created_at),
                "items": [
                    {
                        "product_id": i.product_id,
                        "qty": i.quantity,
                        "price": str(i.unit_price),
                    }
                    for i in items
                ],
            })
        return result

    return await _run(user_id, _q)


@mcp.resource("crm://campaigns/{user_id}")
async def get_campaigns_resource(user_id: int) -> list[dict[str, Any]]:
    """
    Return all campaigns for this company, newest first (max 100).

    Returns: id, name, status, created_at.
    """
    def _q(session, company_id, _actor):
        from models.models import Campaign
        campaigns = session.exec(
            select(Campaign)
            .where(Campaign.company_id == company_id)
            .order_by(Campaign.created_at.desc())
            .limit(100)
        ).all()
        return [
            {"id": c.id, "name": c.name, "status": c.status, "created_at": str(c.created_at)}
            for c in campaigns
        ]

    return await _run(user_id, _q)


# ─── tools (pure / no DB) ─────────────────────────────────────────────────────

@mcp.tool()
def check_icp_qualification(company_size: str, industry: str, employee_count: int = 0) -> dict[str, Any]:
    """
    Check whether a prospect meets the Ideal Customer Profile (ICP).

    USE THIS WHEN: You have a new inbound lead and want to know if it's worth pursuing
    before spending agent time on it.

    ARGS: company_size (str), industry (str), employee_count (int)
    RETURNS: {qualified: bool, score: float, reasons: list}
    SIDE EFFECTS: None — pure in-memory evaluation.
    """
    return service_check_icp_qualification(company_size, industry, employee_count)


@mcp.tool()
def check_guardrails(requested_discount_percent: float) -> dict[str, Any]:
    """
    Enforce discount guardrails — check if a requested discount is within policy.

    USE THIS WHEN: Agent is about to offer a discount and needs to validate it
    against company policy before speaking it to the customer.

    DO NOT USE: To calculate the right discount — this only validates a proposed one.

    ARGS: requested_discount_percent (float 0-100)
    RETURNS: {allowed: bool, max_allowed: float, reason: str}
    SIDE EFFECTS: None — pure in-memory policy check.
    """
    return service_check_guardrails(requested_discount_percent)


@mcp.tool()
def get_call_latency_summary(interaction_id: int) -> dict[str, Any]:
    """
    Return voice pipeline latency breakdown for a completed call interaction.

    USE THIS WHEN: Debugging a slow call or investigating ASR/LLM/TTS timing.
    ARGS: interaction_id (int)
    RETURNS: {asr_ms, llm_ms, tts_ms, total_ms, p95_ms}
    SIDE EFFECTS: None.
    """
    return service_get_call_latency_summary(interaction_id)


# ─── tools (DB-backed, all async via asyncio.to_thread) ───────────────────────

@mcp.tool()
async def get_product_info(product_name: str, user_id: int) -> dict[str, Any]:
    """
    Look up a product by name and return its full details.

    USE THIS WHEN: Customer asks "how much does X cost?" or "do you have Y in stock?"
    during a call. Searches company inventory by fuzzy name match.

    ARGS: product_name (str), user_id (int)
    RETURNS: {name, sku, price, currency, stock, description, note}
    """
    def _q(session, company_id, _actor):
        return service_get_product_info(session, company_id, product_name)
    return await _run(user_id, _q)


@mcp.tool()
async def get_or_create_lead(
    name: str, phone: str, user_id: int, email: str | None = None
) -> dict[str, Any]:
    """
    Find an existing lead by phone number, or create a new one if not found.

    USE THIS WHEN: An inbound call arrives — always call this first to establish
    lead context before speaking. Returns the existing lead or creates a new one.

    DO NOT USE: If you only need to look up (not create) — no equivalent yet,
    this is the primary identity resolution tool.

    ARGS: name (str), phone (str E.164), user_id (int), email (str optional)
    RETURNS: {lead_id, is_new, name, phone, status, ism_stage}
    """
    def _q(session, company_id, actor_user_id):
        return service_get_or_create_lead(session, company_id, actor_user_id, name, phone, email)
    return await _run(user_id, _q)


@mcp.tool()
async def send_communication(
    lead_id: int,
    channels: list[str],
    content: str,
    user_id: int,
    subject: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    """
    Send a message to a lead across one or more channels (email, SMS, WhatsApp).

    USE THIS WHEN: Post-call follow-up, quote delivery, meeting confirmation.
    Respects opt-out status automatically.

    DO NOT USE: During an active call — for real-time utterances use TTS directly.

    ARGS: lead_id (int), channels (list: "email"|"sms"|"whatsapp"), content (str),
          user_id (int), subject (str email subject), email (str override),
          phone (str override)
    RETURNS: {sent_channels: list, message_ids: dict, errors: list}
    SIDE EFFECTS: Writes to communication_history. Deducts channel credits.
    """
    def _q(session, company_id, actor_user_id):
        return service_send_communication(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            channels=channels,
            content=content,
            subject=subject,
            email=email,
            phone=phone,
        )
    return await _run(user_id, _q)


@mcp.tool()
async def sync_product_catalog(user_id: int) -> dict[str, Any]:
    """
    Trigger a product catalog sync from the configured inventory source.

    USE THIS WHEN: Admin requests a refresh after uploading a new CSV or after
    the ERP was updated. Not needed during active calls.

    ARGS: user_id (int)
    RETURNS: {synced_count, skipped_count, errors: list, duration_ms}
    SIDE EFFECTS: Writes to products table.
    """
    def _q(session, company_id, _actor):
        return service_sync_product_catalog(session, company_id)
    return await _run(user_id, _q)


@mcp.tool()
async def get_google_auth_url(user_id: int) -> dict[str, Any]:
    """
    Generate the Google OAuth URL for calendar integration.

    USE THIS WHEN: User initiates Google Calendar connection in Settings.
    Returns a URL the user must visit to grant calendar permissions.

    ARGS: user_id (int)
    RETURNS: {auth_url: str, state: str}
    SIDE EFFECTS: Stores OAuth state in DB for CSRF validation.
    """
    def _q(session, company_id, actor_user_id):
        return service_get_google_auth_url(session, company_id, actor_user_id)
    return await _run(user_id, _q)


@mcp.tool()
async def submit_google_auth_code(user_id: int, code: str) -> dict[str, Any]:
    """
    Exchange a Google OAuth authorization code for calendar access tokens.

    USE THIS WHEN: User returns from Google OAuth consent screen with ?code=...
    Stores refresh token securely for future calendar operations.

    ARGS: user_id (int), code (str — from Google redirect URL)
    RETURNS: {success: bool, calendar_connected: bool, email: str}
    SIDE EFFECTS: Writes OAuth tokens to DB. Enables book_meeting/book_demo.
    """
    def _q(session, company_id, actor_user_id):
        return service_submit_google_auth_code(session, company_id, actor_user_id, code)
    return await _run(user_id, _q)


@mcp.tool()
async def book_meeting(
    lead_id: int,
    proposed_time: str,
    user_id: int,
    meeting_type: str = "demo",
    lead_email: str | None = None,
) -> dict[str, Any]:
    """
    Book a meeting or demo on Google Calendar and send the invite to the lead.

    USE THIS WHEN: Lead agrees to a demo/meeting during the call and specifies a time.

    REQUIRES: Google Calendar OAuth connected (use get_google_auth_url if not set up).

    ARGS: lead_id (int), proposed_time (str ISO-8601), user_id (int),
          meeting_type ("demo"|"followup"|"call"), lead_email (str optional)
    RETURNS: {appointment_id, meeting_link, calendar_event_id, invite_sent: bool}
    SIDE EFFECTS: Creates Google Calendar event + Appointment DB row. Sends email invite.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return await service_book_meeting(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            proposed_time=proposed_time,
            meeting_type=meeting_type,
            lead_email=lead_email,
        )


@mcp.tool()
async def book_demo(
    lead_id: int,
    name: str,
    phone: str,
    demo_date: str,
    products: str,
    user_id: int,
    demo_type: str = "Offline",
    city: str | None = None,
    state: str | None = None,
    pincode: str | None = None,
    email: str | None = None,
    notes: str | None = None,
) -> dict[str, Any]:
    """
    Schedule a product demo (offline or online) with a lead.

    USE THIS WHEN: Lead specifically asks for a product demo / showroom visit.
    Different from book_meeting — this also captures location and product details.

    ARGS: lead_id (int), name (str), phone (str), demo_date (str ISO date),
          products (str comma-sep product names), user_id (int),
          demo_type ("Offline"|"Online"), city, state, pincode, email, notes
    RETURNS: {appointment_id, demo_type, demo_date, confirmation_sent: bool}
    SIDE EFFECTS: Creates Appointment DB row. Sends confirmation via preferred channel.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return await service_book_demo(
            session=session,
            company_id=company_id,
            actor_user_id=actor_user_id,
            lead_id=lead_id,
            name=name,
            phone=phone,
            demo_date=demo_date,
            products=products,
            demo_type=demo_type,
            city=city,
            state=state,
            pincode=pincode,
            email=email,
            notes=notes,
        )


@mcp.tool()
async def search_knowledge_base(
    query: str,
    user_id: int,
    collection: str = "all",
    n_results: int = 5,
) -> dict[str, Any]:
    """
    Search the company knowledge base using hybrid RAG (vector + BM25 + rerank).

    USE THIS WHEN: Customer asks a product, policy, or feature question during a call.
    Returns the most relevant KB chunks to answer it.

    DO NOT USE: For CRM data (leads, calls, orders) — those have their own tools.
    DO NOT USE: For live inventory levels — use get_product_info instead.

    ARGS: query (str), user_id (int), collection ("all"|"products"|"objections"|
          "competitors"|"playbooks"|"coaching"|"sops"|"transcripts"), n_results (int max 10)
    RETURNS: {text: str ready-to-inject, chunks: int}
    LATENCY: ~80ms on warm vector DB.
    """
    company_id_holder: list[int | None] = [None]

    def _resolve(session, company_id, _actor):
        company_id_holder[0] = company_id
        return None

    await _run(user_id, _resolve)
    company_id = company_id_holder[0]
    if not company_id:
        return {"error": "User context not found"}

    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = await asyncio.to_thread(
            rag_search, query,
            company_id=company_id,
            collection=collection,
            n_results=n_results,
        )
        return {"text": format_for_prompt(results), "chunks": len(results)}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def get_objection_rebuttal(objection: str, user_id: int) -> dict[str, Any]:
    """
    Retrieve a proven rebuttal for an objection from the KB.

    USE THIS WHEN: Customer says "too expensive", "not interested", "call back later",
    "already have one", or any other resistance signal during the call.

    DO NOT USE: For factual product questions — use search_knowledge_base instead.

    ARGS: objection (str — what the customer said), user_id (int)
    RETURNS: {rebuttal: str ready to speak, source: str KB doc title}
    LATENCY: ~80ms (RAG search).
    """
    company_id_holder: list[int | None] = [None]

    def _resolve(session, company_id, _actor):
        company_id_holder[0] = company_id
        return None

    await _run(user_id, _resolve)
    company_id = company_id_holder[0]
    if not company_id:
        return {"error": "User context not found"}

    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = await asyncio.to_thread(
            rag_search, objection,
            company_id=company_id,
            collection="objections",
            n_results=3,
        )
        return {"rebuttal": format_for_prompt(results) or "No rebuttal found in KB."}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def get_competitor_intel(competitor_name: str, user_id: int) -> dict[str, Any]:
    """
    Pull a competitor battle card from the KB.

    USE THIS WHEN: Customer mentions a competitor by name ("I'm also looking at X").
    Returns talking points and differentiation angles.

    ARGS: competitor_name (str), user_id (int)
    RETURNS: {intel: str battle card content, competitor: str}
    LATENCY: ~80ms (RAG search).
    """
    company_id_holder: list[int | None] = [None]

    def _resolve(session, company_id, _actor):
        company_id_holder[0] = company_id
        return None

    await _run(user_id, _resolve)
    company_id = company_id_holder[0]
    if not company_id:
        return {"error": "User context not found"}

    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = await asyncio.to_thread(
            rag_search, competitor_name,
            company_id=company_id,
            collection="competitors",
            n_results=3,
        )
        return {
            "intel": format_for_prompt(results) or f"No battle card found for {competitor_name}.",
            "competitor": competitor_name,
        }
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def enrich_lead(lead_id: int, user_id: int) -> dict[str, Any]:
    """
    Enrich a lead with Apollo.io data (company, title, LinkedIn, industry).

    USE THIS WHEN: New lead was just created and you want to fill in missing
    firmographic details before the first call. Run this in the pre-call workflow.

    DO NOT USE: For leads that were already enriched recently (enrichment is rate-limited).

    ARGS: lead_id (int), user_id (int)
    RETURNS: {status: "enriched"|"skipped"|"error", lead_id, fields_updated: list}
    SIDE EFFECTS: Writes enriched fields to the leads table.
    LATENCY: ~300ms (Apollo API call).
    """
    def _q(session, company_id, actor_user_id):
        try:
            from services.leads.demand_generation_service import enrich_lead_if_needed
            enrich_lead_if_needed(
                session=session,
                company_id=company_id,
                actor_user_id=actor_user_id,
                lead_id=lead_id,
            )
            return {"status": "enriched", "lead_id": lead_id}
        except Exception as exc:
            return {"error": str(exc)}
    return await _run(user_id, _q)


@mcp.tool()
async def score_lead_demand(lead_id: int, user_id: int) -> dict[str, Any]:
    """
    Compute the demand-generation ICP fit score for a lead (0.0–1.0).

    USE THIS WHEN: Prioritising which cold leads to call in a campaign batch.

    NOTE: This uses the demand_generation scorer (ICP rules). For the ML-based
    conversion probability scorer, use the 'score_lead' tool via execute_mcp_tool.

    ARGS: lead_id (int), user_id (int)
    RETURNS: {lead_id, score: float, tier: str, factors: list}
    """
    def _q(session, company_id, _actor):
        try:
            from services.leads.demand_generation_service import score_lead as _score
            return _score(session=session, company_id=company_id, lead_id=lead_id)
        except Exception as exc:
            return {"error": str(exc)}
    return await _run(user_id, _q)


@mcp.tool()
async def get_ism_stage(lead_id: int, user_id: int) -> dict[str, Any]:
    """
    Return the current ISM stage for a lead.

    USE THIS WHEN: Before an outreach decision — need to know whether to
    call, email, or send a quote based on where this lead sits in the funnel.

    ARGS: lead_id (int), user_id (int)
    RETURNS: {lead_id, ism_stage: str}
    """
    def _q(session, company_id, _actor):
        lead = session.get(Lead, lead_id)
        if not lead or lead.company_id != company_id:
            return {"error": f"Lead {lead_id} not found"}
        return {"lead_id": lead_id, "ism_stage": lead.ism_stage or "new"}
    return await _run(user_id, _q)


@mcp.tool()
async def advance_ism_stage(lead_id: int, user_id: int) -> dict[str, Any]:
    """
    Run one ISM cycle: advance the lead's stage and dispatch the best outreach channel.

    USE THIS WHEN: Automation worker processes a lead's scheduled next action.
    This is the core ISM orchestration step — it picks the right channel and sends.

    DO NOT USE: During an active call — this is a background/automation operation.

    ARGS: lead_id (int), user_id (int)
    RETURNS: {stage_before, stage_after, action_taken, channel_used}
    SIDE EFFECTS: May send email/SMS/WhatsApp. Advances ISM stage in DB.
    """
    def _q(session, company_id, actor_user_id):
        try:
            from agents.ism_orchestrator import run_ism_cycle
            result = run_ism_cycle(
                session=session,
                company_id=company_id,
                lead_id=lead_id,
                actor_user_id=actor_user_id,
            )
            return result if isinstance(result, dict) else {"result": str(result)}
        except Exception as exc:
            return {"error": str(exc)}
    return await _run(user_id, _q)


@mcp.tool()
async def get_pipeline_funnel(user_id: int) -> dict[str, Any]:
    """
    Return lead counts at each ISM stage (funnel snapshot).

    USE THIS WHEN: Dashboard needs a funnel view, or an agent needs to understand
    pipeline health before a coaching/strategy session.

    ARGS: user_id (int)
    RETURNS: {stage_name: lead_count, ...} — one entry per stage with leads in it.
    """
    from sqlalchemy import func

    def _q(session, company_id, _actor):
        rows = session.exec(
            select(Lead.ism_stage, func.count(Lead.id).label("count"))
            .where(Lead.company_id == company_id)
            .group_by(Lead.ism_stage)
        ).all()
        return {r[0] or "unknown": r[1] for r in rows}

    return await _run(user_id, _q)


@mcp.tool()
async def get_engagement_summary(user_id: int, days: int = 30) -> dict[str, Any]:
    """
    Return engagement metrics for the last N days.

    USE THIS WHEN: Weekly/daily performance review needs call, email, open,
    reply, and conversion counts in one shot.

    ARGS: user_id (int), days (int lookback window, default 30)
    RETURNS: {calls_made, emails_sent, whatsapp_sent, opens, replies,
              conversions, conversion_rate, avg_call_duration_s}
    """
    def _q(session, company_id, _actor):
        try:
            from services.analytics.analytics_service import get_engagement_summary as _get
            return _get(session=session, company_id=company_id, days=days)
        except Exception as exc:
            return {"error": str(exc)}
    return await _run(user_id, _q)


@mcp.tool()
async def update_lead_status(
    lead_id: int, new_status: str, user_id: int, notes: str = ""
) -> dict[str, Any]:
    """
    Update a lead's CRM status field and optionally append call notes.

    USE THIS WHEN: Call ends and the outcome needs to be logged.
    Always call this at the end of every call — even if status didn't change,
    notes from the call are valuable.

    ARGS: lead_id (int), new_status (str e.g. 'Demo Scheduled', 'Follow-up',
          'Not Qualified', 'Closed Won', 'Closed Lost'), user_id (int), notes (str)
    RETURNS: {lead_id, new_status, updated_at}
    SIDE EFFECTS: Writes to leads table. May trigger automation workflow.
    """
    def _q(session, company_id, _actor):
        from models.models import utc_now
        lead = session.get(Lead, lead_id)
        if not lead or lead.company_id != company_id:
            return {"error": f"Lead {lead_id} not found"}
        lead.status = new_status
        if notes:
            lead.notes = f"{lead.notes or ''}\n{notes}".strip()
        lead.updated_at = utc_now()
        session.add(lead)
        session.commit()
        return {"lead_id": lead_id, "new_status": new_status, "updated_at": lead.updated_at.isoformat()}
    return await _run(user_id, _q)


@mcp.tool()
async def enroll_in_campaign(lead_id: int, campaign_id: int, user_id: int) -> dict[str, Any]:
    """
    Enroll a lead into a drip campaign.

    USE THIS WHEN: After qualifying a lead, you want to start an automated
    nurture sequence (email + WhatsApp cadence).

    DO NOT USE: If the lead has opted out of any channel — check opt-out first.

    ARGS: lead_id (int), campaign_id (int), user_id (int)
    RETURNS: {enrolled: bool, lead_id, campaign_id}
    SIDE EFFECTS: Writes campaign enrollment. First campaign message may fire immediately.
    """
    def _q(session, company_id, actor_user_id):
        try:
            from services.campaign.campaign_service import enroll_leads
            enroll_leads(
                session=session,
                campaign_id=campaign_id,
                lead_ids=[lead_id],
                company_id=company_id,
                actor_user_id=actor_user_id,
            )
            return {"enrolled": True, "lead_id": lead_id, "campaign_id": campaign_id}
        except Exception as exc:
            return {"error": str(exc)}
    return await _run(user_id, _q)


@mcp.tool()
async def create_quote_for_lead(
    lead_id: int,
    user_id: int,
    items: list[dict[str, Any]],
    notes: str = "",
    valid_days: int = 30,
) -> dict[str, Any]:
    """
    Create a product quote for a lead and save it as a draft.

    USE THIS WHEN: Lead asks for pricing during a call and you want to generate
    a formal quote document that can be sent via email/WhatsApp.

    ARGS: lead_id (int), user_id (int),
          items (list of {product_id, quantity, unit_price}),
          notes (str), valid_days (int)
    RETURNS: {quote_id, lead_id, status: "draft", items: int}
    SIDE EFFECTS: Writes Quote + QuoteItem rows to DB. Does NOT send the quote.
    Use send_communication to deliver it after creation.
    """
    def _q(session, company_id, actor_user_id):
        from models.models import Quote, QuoteItem
        try:
            quote = Quote(
                lead_id=lead_id,
                company_id=company_id,
                created_by=actor_user_id,
                notes=notes,
                valid_days=valid_days,
                status="draft",
            )
            session.add(quote)
            session.flush()
            for item in items:
                session.add(QuoteItem(
                    quote_id=quote.id,
                    product_id=item.get("product_id"),
                    quantity=item.get("quantity", 1),
                    unit_price=item.get("unit_price", 0),
                ))
            session.commit()
            return {"quote_id": quote.id, "lead_id": lead_id, "status": "draft", "items": len(items)}
        except Exception as exc:
            session.rollback()
            return {"error": str(exc)}
    return await _run(user_id, _q)


# ─── async orchestration tools (already async, keep as-is) ────────────────────

@mcp.tool()
async def run_pre_call_workflow(lead_id: int, user_id: int) -> dict[str, Any]:
    """
    Run the full pre-call enrichment workflow in parallel.

    USE THIS WHEN: Agent is about to start a call and needs a complete briefing.
    Runs: KB context search + lead research + ICP score + interaction history
    in parallel and returns a single combined dict.

    DO NOT USE: During an active call — this is a pre-call preparation tool.

    ARGS: lead_id (int), user_id (int)
    RETURNS: {kb_context, lead_data, icp_score, interaction_history}
    LATENCY: ~200ms (parallel execution).
    """
    company_id_holder: list[int | None] = [None]
    actor_holder: list[int | None] = [None]

    def _resolve(session, company_id, actor_user_id):
        company_id_holder[0] = company_id
        actor_holder[0] = actor_user_id
        return None

    await _run(user_id, _resolve)
    if not company_id_holder[0]:
        return {"error": "User context not found"}

    try:
        from agents.orchestrator import run_pre_call
        return await run_pre_call(
            lead_id=lead_id,
            company_id=company_id_holder[0],
            actor_user_id=actor_holder[0],
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def ask_rio(query: str, user_id: int, lead_id: int | None = None) -> dict[str, Any]:
    """
    Ask Rio a freeform sales question. The supervisor routes to the right agent(s).

    USE THIS WHEN: The query doesn't map to a specific tool — use this as the
    catch-all that routes through the full agent pipeline.

    Examples:
    - "What are the best objection rebuttals for pricing?"
    - "How many deals are in negotiation this month?"
    - "Prepare a briefing for lead 42 before my call"
    - "Which leads should I call first today?"

    DO NOT USE: If you know the right specific tool — direct calls are faster.

    ARGS: query (str), user_id (int), lead_id (int optional)
    RETURNS: Whatever the orchestrator decides is most relevant.
    LATENCY: 500ms–2s depending on how many sub-agents are invoked.
    """
    company_id_holder: list[int | None] = [None]
    actor_holder: list[int | None] = [None]

    def _resolve(session, company_id, actor_user_id):
        company_id_holder[0] = company_id
        actor_holder[0] = actor_user_id
        return None

    await _run(user_id, _resolve)
    if not company_id_holder[0]:
        return {"error": "User context not found"}

    try:
        from agents.orchestrator import ask
        return await ask(
            query=query,
            company_id=company_id_holder[0],
            actor_user_id=actor_holder[0],
            lead_id=lead_id,
        )
    except Exception as exc:
        return {"error": str(exc)}


# ─── SSE transport (mount on FastAPI at /mcp) ─────────────────────────────────

def get_mcp_asgi_app():
    """
    Return an ASGI app for the MCP server with SSE transport.

    Mount this on the FastAPI app at /mcp:
        app.mount("/mcp", get_mcp_asgi_app())

    Clients connect via:
        SSE endpoint:     GET  /mcp/sse
        Message endpoint: POST /mcp/messages
    """
    if not _FASTMCP_AVAILABLE or mcp is None:
        logger.warning("[MCP] FastMCP not available — MCP server disabled.")
        return None

    try:
        return mcp.http_app(transport="sse")
    except Exception:
        pass

    for method_name in ("get_asgi_app", "streamable_http_app", "sse_app"):
        try:
            return getattr(mcp, method_name)()
        except AttributeError:
            continue

    logger.warning("[MCP] Could not build SSE ASGI app — fastmcp API not found.")
    return None


if __name__ == "__main__":
    import sys
    transport = sys.argv[1] if len(sys.argv) > 1 else "stdio"
    mcp.run(transport=transport)
