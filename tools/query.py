"""Query Tool - Agentic SQL + Lead Status queries"""

from sqlmodel import Session, select, text
from database import engine, Lead, Interaction, Product

def check_lead_status(lead_id: int) -> dict:
    """
    Get comprehensive lead status and history (DETERMINISTIC).
    
    Args:
        lead_id: ID of the lead
    
    Returns:
        {
            "lead_id": int,
            "name": str,
            "email": str,
            "phone": str,
            "status": str,
            "icp_score": float,
            "interactions_count": int,
            "last_interaction": str,
            "created_date": str,
            "message": str
        }
    """
    with Session(engine) as session:
        lead = session.get(Lead, lead_id)
        
        if not lead:
            return {"error": f"Lead {lead_id} not found"}
        
        # Count interactions
        interactions = session.exec(
            select(Interaction).where(Interaction.lead_id == lead_id)
        ).all()
        
        last_interaction = None
        if interactions:
            last_interaction = max(interactions, key=lambda x: x.timestamp).timestamp.isoformat()
        
        return {
            "lead_id": lead_id,
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone,
            "status": lead.status,
            "source": lead.source,
            "enrichment_status": lead.enrichment_status,
            "interactions_count": len(interactions),
            "last_interaction": last_interaction,
            "created_date": lead.created_at.isoformat() if lead.created_at else None,
            "message": f"✓ Lead {lead.name} has {len(interactions)} interactions"
        }

def semantic_query(question: str, query_type: str = "leads") -> dict:
    """
    Agentic SQL query based on semantic question (AGENTIC - 20% use case).
    
    This tool lets the agent ask natural language questions and returns relevant data.
    Examples:
    - "Show me leads from Tech industry"
    - "How many leads are qualified?"
    - "What's our top performing product?"
    
    Args:
        question: Natural language query
        query_type: "leads", "products", "interactions"
    
    Returns:
        {
            "results": list,
            "count": int,
            "query_type": str,
            "message": str
        }
    """
    with Session(engine) as session:
        question_lower = question.lower()
        results = []
        
        # Lead queries
        if query_type == "leads" or "lead" in question_lower:
            if "tech" in question_lower or "technology" in question_lower:
                leads = session.exec(
                    select(Lead).where(Lead.source.ilike("%tech%"))
                ).all()
            elif "qualified" in question_lower:
                leads = session.exec(
                    select(Lead).where(Lead.status == "Qualified")
                ).all()
            elif "new" in question_lower:
                leads = session.exec(
                    select(Lead).where(Lead.status == "New")
                ).all()
            else:
                leads = session.exec(select(Lead)).all()
            
            results = [
                {
                    "id": l.id,
                    "name": l.name,
                    "email": l.email,
                    "status": l.status,
                    "source": l.source
                }
                for l in leads
            ]
        
        # Product queries
        elif query_type == "products" or "product" in question_lower:
            if "stock" in question_lower or "available" in question_lower:
                products = session.exec(
                    select(Product).where(Product.stock > 0)
                ).all()
            else:
                products = session.exec(select(Product)).all()
            
            results = [
                {
                    "name": p.name,
                    "price": p.price,
                    "stock": p.stock
                }
                for p in products
            ]
        
        # Interaction queries
        elif query_type == "interactions" or "interaction" in question_lower:
            interactions = session.exec(select(Interaction)).all()
            results = [
                {
                    "type": i.type,
                    "lead_id": i.lead_id,
                    "timestamp": i.timestamp.isoformat() if i.timestamp else None
                }
                for i in interactions
            ]
        
        return {
            "results": results,
            "count": len(results),
            "query_type": query_type,
            "message": f"✓ Found {len(results)} {query_type}"
        }

def search_leads_by_criteria(criteria: dict) -> dict:
    """
    Search leads using multiple criteria (DETERMINISTIC).
    
    Args:
        criteria: Dict with keys like 'name', 'email', 'status', 'source'
    
    Returns:
        {
            "found": bool,
            "results": list,
            "count": int
        }
    """
    with Session(engine) as session:
        query = select(Lead)
        
        if "name" in criteria:
            query = query.where(Lead.name.ilike(f"%{criteria['name']}%"))
        if "email" in criteria:
            query = query.where(Lead.email.ilike(f"%{criteria['email']}%"))
        if "status" in criteria:
            query = query.where(Lead.status == criteria["status"])
        if "source" in criteria:
            query = query.where(Lead.source.ilike(f"%{criteria['source']}%"))
        
        leads = session.exec(query).all()
        
        return {
            "found": len(leads) > 0,
            "results": [
                {
                    "id": l.id,
                    "name": l.name,
                    "email": l.email,
                    "status": l.status,
                    "source": l.source
                }
                for l in leads
            ],
            "count": len(leads)
        }
