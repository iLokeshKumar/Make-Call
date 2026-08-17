"""Query Tool — Lead status checks and semantic KB search."""

from typing import Optional

from langchain_core.tools import tool
from sqlmodel import Session, select
from database import engine
from models.models import Lead, Interaction


@tool
def check_lead_status(lead_id: int) -> dict:
    """
    Get comprehensive lead status and interaction history for a given lead_id.
    Use this to look up what we know about a lead before or during a call.
    """
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)

        if not lead:
            return {"error": f"Lead {lead_id} not found"}

        interactions = session.exec(
            select(Interaction).where(Interaction.lead_id == lead_id)
        ).all()

        last_interaction = None
        if interactions:
            last_interaction = max(interactions, key=lambda x: x.started_at).started_at.isoformat()

        return {
            "lead_id": lead_id,
            "name": lead.name,
            "email": lead.email,
            "phone": lead.normalized_phone,
            "status": lead.status,
            "ism_stage": lead.ism_stage,
            "source": lead.source,
            "enrichment_status": lead.enrichment_status,
            "interactions_count": len(interactions),
            "last_interaction": last_interaction,
            "created_date": lead.created_at.isoformat() if lead.created_at else None,
            "message": f"Lead {lead.name} has {len(interactions)} interactions",
        }


@tool
def semantic_query(query: str, collection: str = "all", company_id: Optional[int] = None) -> str:
    """
    Searches the Rio knowledge base semantically for relevant context.
    Use this to find product information, objection handling strategies,
    competitor intelligence, playbooks, or coaching tips.
    Collections: products, objections, competitors, playbooks, coaching, sops, transcripts, all.
    Returns the top matching knowledge chunks as formatted text.
    """
    if not company_id:
        return "company_id is required to search the knowledge base."
    try:
        from services.rag.query_engine import format_for_prompt, search as rag_search
        results = rag_search(query, company_id=company_id, collection=collection, n_results=5)
        return format_for_prompt(results)
    except Exception as exc:
        return f"Knowledge base search unavailable: {exc}"
