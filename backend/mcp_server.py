from __future__ import annotations

import logging
from typing import Any

try:
    from fastmcp import FastMCP
    _FASTMCP_AVAILABLE = True
except ImportError:
    FastMCP = None
    _FASTMCP_AVAILABLE = False

from sqlmodel import Session, select

from database import engine
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


def _resolve_user_context(session: Session, user_id: int | None) -> tuple[int | None, int | None]:
    if not user_id:
        return None, None
    user = session.get(User, user_id)
    if not user:
        return None, None
    return user.company_id, user.id


@mcp.resource("crm://leads/{user_id}")
def get_leads_summary(user_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        leads = session.exec(
            select(Lead).where(Lead.company_id == company_id).order_by(Lead.created_at.desc())
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


@mcp.resource("crm://inventory/{user_id}")
def get_inventory(user_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        products = session.exec(
            select(Product).where(Product.company_id == company_id).order_by(Product.created_at.desc())
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


@mcp.resource("crm://interactions/{user_id}/{lead_id}")
def get_lead_interactions(user_id: int, lead_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        interactions = session.exec(
            select(Interaction).where(
                Interaction.company_id == company_id,
                Interaction.lead_id == lead_id,
            ).order_by(Interaction.started_at.desc())
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


@mcp.resource("crm://appointments/{user_id}")
def get_appointments(user_id: int) -> list[dict[str, Any]]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        appointments = session.exec(
            select(Appointment).where(Appointment.company_id == company_id).order_by(Appointment.appointment_time.desc())
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


@mcp.tool()
def check_icp_qualification(company_size: str, industry: str, employee_count: int = 0) -> dict[str, Any]:
    return service_check_icp_qualification(company_size, industry, employee_count)


@mcp.tool()
def get_product_info(product_name: str, user_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        return service_get_product_info(session, company_id, product_name)


@mcp.tool()
def check_guardrails(requested_discount_percent: float) -> dict[str, Any]:
    return service_check_guardrails(requested_discount_percent)


@mcp.tool()
def get_or_create_lead(name: str, phone: str, user_id: int, email: str | None = None) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_get_or_create_lead(session, company_id, actor_user_id, name, phone, email)


@mcp.tool()
async def book_meeting(
    lead_id: int,
    proposed_time: str,
    user_id: int,
    meeting_type: str = "demo",
    lead_email: str | None = None,
) -> dict[str, Any]:
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
def send_communication(
    lead_id: int,
    channels: list[str],
    content: str,
    user_id: int,
    subject: str | None = None,
    email: str | None = None,
    phone: str | None = None,
) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
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


@mcp.tool()
def sync_product_catalog(user_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        return service_sync_product_catalog(session, company_id)


@mcp.tool()
def get_call_latency_summary(interaction_id: int) -> dict[str, Any]:
    return service_get_call_latency_summary(interaction_id)


@mcp.tool()
def get_google_auth_url(user_id: int) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_get_google_auth_url(session, company_id, actor_user_id)


@mcp.tool()
def submit_google_auth_code(user_id: int, code: str) -> dict[str, Any]:
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        return service_submit_google_auth_code(session, company_id, actor_user_id, code)


# Expanded resources, agent tools, and SSE transport

@mcp.resource("crm://knowledge/{user_id}/{collection}")
def get_knowledge_collection(user_id: int, collection: str) -> list[dict[str, Any]]:
    """List knowledge base documents in a given collection for this company.

    Valid collections: products, objections, competitors, playbooks,
    coaching, sops, transcripts, or 'all' for every collection.
    """
    with Session(engine) as session:
        from models.models import KnowledgeDocument
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        q = select(KnowledgeDocument).where(
            KnowledgeDocument.company_id == company_id,
            KnowledgeDocument.is_active == True,  # noqa: E712
        )
        if collection != "all":
            q = q.where(KnowledgeDocument.collection == collection)
        docs = session.exec(q.limit(200)).all()
        return [
            {"id": d.id, "collection": d.collection, "title": d.title,
             "tags": d.tags, "last_indexed_at": str(d.last_indexed_at)}
            for d in docs
        ]


@mcp.resource("crm://pipeline/{user_id}")
def get_pipeline(user_id: int) -> dict[str, Any]:
    """Return lead counts at each ISM stage (funnel view)."""
    from sqlalchemy import func
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {}
        rows = session.exec(
            select(Lead.ism_stage, func.count(Lead.id).label("count"))
            .where(Lead.company_id == company_id)
            .group_by(Lead.ism_stage)
        ).all()
        return {r[0] or "unknown": r[1] for r in rows}


@mcp.resource("crm://analytics/{user_id}")
def get_analytics_summary(user_id: int) -> dict[str, Any]:
    """Return a 30-day engagement summary (calls, emails, opens, replies)."""
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {}
        try:
            from services.analytics.analytics_service import get_engagement_summary
            return get_engagement_summary(session=session, company_id=company_id, days=30)
        except Exception as exc:
            return {"error": str(exc)}


@mcp.resource("crm://quotes/{user_id}/{lead_id}")
def get_lead_quotes(user_id: int, lead_id: int) -> list[dict[str, Any]]:
    """Return all quotes for a lead."""
    with Session(engine) as session:
        from models.models import Quote, QuoteItem
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        quotes = session.exec(
            select(Quote).where(
                Quote.company_id == company_id, Quote.lead_id == lead_id
            ).order_by(Quote.created_at.desc())
        ).all()
        result = []
        for q in quotes:
            items = session.exec(select(QuoteItem).where(QuoteItem.quote_id == q.id)).all()
            result.append({
                "id": q.id, "status": q.status, "valid_days": q.valid_days,
                "notes": q.notes, "created_at": str(q.created_at),
                "items": [{"product_id": i.product_id, "qty": i.quantity, "price": str(i.unit_price)}
                          for i in items],
            })
        return result


@mcp.resource("crm://campaigns/{user_id}")
def get_campaigns_resource(user_id: int) -> list[dict[str, Any]]:
    """Return all active campaigns for this company."""
    with Session(engine) as session:
        from models.models import Campaign
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return []
        campaigns = session.exec(
            select(Campaign).where(Campaign.company_id == company_id)
            .order_by(Campaign.created_at.desc()).limit(100)
        ).all()
        return [{"id": c.id, "name": c.name, "status": c.status,
                 "created_at": str(c.created_at)} for c in campaigns]


@mcp.tool()
def search_knowledge_base(
    query: str,
    user_id: int,
    collection: str = "all",
    n_results: int = 5,
) -> dict[str, Any]:
    """Search the company knowledge base using hybrid RAG (vector + BM25 + rerank).

    Args:
        query: Natural-language search query.
        user_id: Authenticated user ID (resolves company).
        collection: KB collection or 'all'. Options: products, objections,
                    competitors, playbooks, coaching, sops, transcripts.
        n_results: Max results to return (default 5).
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(query, company_id=company_id, collection=collection, n_results=n_results)
        return {"text": format_for_prompt(results), "chunks": len(results)}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def enrich_lead(lead_id: int, user_id: int) -> dict[str, Any]:
    """Enrich a lead with Apollo.io data (company, title, LinkedIn, industry).

    Args:
        lead_id: ID of the lead to enrich.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        try:
            from services.leads.demand_generation_service import enrich_lead_if_needed
            enrich_lead_if_needed(session=session, company_id=company_id,
                                  actor_user_id=actor_user_id, lead_id=lead_id)
            return {"status": "enriched", "lead_id": lead_id}
        except Exception as exc:
            return {"error": str(exc)}


@mcp.tool()
def score_lead(lead_id: int, user_id: int) -> dict[str, Any]:
    """Compute and persist the ICP fit score for a lead (0.0 – 1.0).

    Args:
        lead_id: ID of the lead to score.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        try:
            from services.leads.demand_generation_service import score_lead as _score
            result = _score(session=session, company_id=company_id, lead_id=lead_id)
            return result
        except Exception as exc:
            return {"error": str(exc)}


@mcp.tool()
def get_ism_stage(lead_id: int, user_id: int) -> dict[str, Any]:
    """Return the current ISM stage for a lead.

    Args:
        lead_id: ID of the lead.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        lead = session.get(Lead, lead_id)
        if not lead or lead.company_id != company_id:
            return {"error": f"Lead {lead_id} not found"}
        return {"lead_id": lead_id, "ism_stage": lead.ism_stage or "new"}


@mcp.tool()
def advance_ism_stage(lead_id: int, user_id: int) -> dict[str, Any]:
    """Run one ISM cycle: advance stage and dispatch the best outreach channel.

    Args:
        lead_id: ID of the lead.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        try:
            from agents.ism_orchestrator import run_ism_cycle
            result = run_ism_cycle(session=session, company_id=company_id,
                                   lead_id=lead_id, actor_user_id=actor_user_id)
            return result if isinstance(result, dict) else {"result": str(result)}
        except Exception as exc:
            return {"error": str(exc)}


@mcp.tool()
def get_pipeline_funnel(user_id: int) -> dict[str, Any]:
    """Return lead counts at each ISM stage.

    Args:
        user_id: Authenticated user ID.
    """
    from sqlalchemy import func
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        rows = session.exec(
            select(Lead.ism_stage, func.count(Lead.id).label("count"))
            .where(Lead.company_id == company_id)
            .group_by(Lead.ism_stage)
        ).all()
        return {r[0] or "unknown": r[1] for r in rows}


@mcp.tool()
def get_engagement_summary(user_id: int, days: int = 30) -> dict[str, Any]:
    """Return engagement metrics for the last N days (calls, emails, opens, replies).

    Args:
        user_id: Authenticated user ID.
        days: Lookback window in days (default 30).
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        try:
            from services.analytics.analytics_service import get_engagement_summary as _get
            return _get(session=session, company_id=company_id, days=days)
        except Exception as exc:
            return {"error": str(exc)}


@mcp.tool()
def get_objection_rebuttal(objection: str, user_id: int) -> dict[str, Any]:
    """Retrieve a proven rebuttal for an objection from the KB.

    Args:
        objection: The objection raised by the lead.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(objection, company_id=company_id, collection="objections", n_results=3)
        return {"rebuttal": format_for_prompt(results) or "No rebuttal found in KB."}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def get_competitor_intel(competitor_name: str, user_id: int) -> dict[str, Any]:
    """Pull competitor battle card from the KB.

    Args:
        competitor_name: Name of the competitor mentioned by the lead.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
    try:
        from services.rag.query_engine import search as rag_search, format_for_prompt
        results = rag_search(competitor_name, company_id=company_id, collection="competitors", n_results=3)
        return {"intel": format_for_prompt(results) or f"No battle card found for {competitor_name}."}
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
def update_lead_status(lead_id: int, new_status: str, user_id: int, notes: str = "") -> dict[str, Any]:
    """Update a lead's CRM status.

    Args:
        lead_id: ID of the lead.
        new_status: New status string (e.g. 'Demo Scheduled', 'Follow-up', 'Not Qualified').
        user_id: Authenticated user ID.
        notes: Optional notes to attach.
    """
    with Session(engine) as session:
        company_id, _ = _resolve_user_context(session, user_id)
        if not company_id:
            return {"error": "User context not found"}
        lead = session.get(Lead, lead_id)
        if not lead or lead.company_id != company_id:
            return {"error": f"Lead {lead_id} not found"}
        lead.status = new_status
        if notes:
            lead.notes = f"{lead.notes or ''}\n{notes}".strip()
        session.add(lead)
        session.commit()
        return {"lead_id": lead_id, "new_status": new_status}


@mcp.tool()
def enroll_in_campaign(lead_id: int, campaign_id: int, user_id: int) -> dict[str, Any]:
    """Enroll a lead into a drip campaign.

    Args:
        lead_id: ID of the lead.
        campaign_id: ID of the campaign.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        try:
            from services.campaign.campaign_service import enroll_leads
            result = enroll_leads(session=session, campaign_id=campaign_id,
                                  lead_ids=[lead_id], company_id=company_id,
                                  actor_user_id=actor_user_id)
            return {"enrolled": True, "lead_id": lead_id, "campaign_id": campaign_id}
        except Exception as exc:
            return {"error": str(exc)}


@mcp.tool()
def create_quote_for_lead(
    lead_id: int,
    user_id: int,
    items: list[dict[str, Any]],
    notes: str = "",
    valid_days: int = 30,
) -> dict[str, Any]:
    """Create a product quote for a lead.

    Args:
        lead_id: ID of the lead.
        user_id: Authenticated user ID.
        items: List of {product_id, quantity, unit_price} dicts.
        notes: Optional notes on the quote.
        valid_days: Days the quote is valid.
    """
    with Session(engine) as session:
        from models.models import Quote, QuoteItem
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
        try:
            quote = Quote(lead_id=lead_id, company_id=company_id, created_by=actor_user_id,
                          notes=notes, valid_days=valid_days, status="draft")
            session.add(quote)
            session.flush()
            for item in items:
                session.add(QuoteItem(quote_id=quote.id, product_id=item.get("product_id"),
                                      quantity=item.get("quantity", 1),
                                      unit_price=item.get("unit_price", 0)))
            session.commit()
            return {"quote_id": quote.id, "lead_id": lead_id, "status": "draft", "items": len(items)}
        except Exception as exc:
            session.rollback()
            return {"error": str(exc)}


@mcp.tool()
async def run_pre_call_workflow(lead_id: int, user_id: int) -> dict[str, Any]:
    """Run the full pre-call enrichment workflow (KB search + lead research + ICP score).

    Returns kb_context, lead_data, icp_score, interaction_history.

    Args:
        lead_id: ID of the lead being called.
        user_id: Authenticated user ID.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
    try:
        from agents.orchestrator import run_pre_call
        return await run_pre_call(lead_id=lead_id, company_id=company_id,
                                  actor_user_id=actor_user_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool()
async def ask_rio(query: str, user_id: int, lead_id: int | None = None) -> dict[str, Any]:
    """Ask Rio a freeform sales question. The supervisor routes to the right agent(s).

    Examples:
    - "What are the best objection rebuttals for pricing?"
    - "How many deals are in negotiation this month?"
    - "Prepare a briefing for lead 42 before my call"

    Args:
        query: Natural-language question or instruction.
        user_id: Authenticated user ID.
        lead_id: Optional lead ID for context.
    """
    with Session(engine) as session:
        company_id, actor_user_id = _resolve_user_context(session, user_id)
        if not company_id or not actor_user_id:
            return {"error": "User context not found"}
    try:
        from agents.orchestrator import ask
        return await ask(query=query, company_id=company_id,
                         actor_user_id=actor_user_id, lead_id=lead_id)
    except Exception as exc:
        return {"error": str(exc)}


# SSE Transport (mount on FastAPI at /mcp)

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
