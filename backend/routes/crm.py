import logging
import io
import pandas as pd
import requests
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlmodel import Session, select, func, text
from database import get_session, engine
from models.models import Lead, LeadCreate, Product, Interaction, Outcome, ApolloSearch, SystemSettings, User
from utils.config import APOLLO_API_KEY
from auth import RoleChecker, get_current_active_user
from enrichment_service import enrich_lead_cascade
from utils.phone import normalize_phone

logger = logging.getLogger(__name__)
router = APIRouter(tags=["CRM & Settings"])

@router.get("/leads", response_model=List[Lead])
async def get_leads(session: Session = Depends(get_session)):
    """Fetch all leads from the database."""
    return session.exec(select(Lead).order_by(Lead.created_at.desc())).all()

@router.post("/leads", response_model=Lead)
async def create_lead(
    lead: LeadCreate, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Create a new lead."""
    db_lead = Lead.model_validate(lead)
    db_lead.phone = normalize_phone(db_lead.phone)
    db_lead.created_by = current_user.username
    if not db_lead.source:
        db_lead.source = "Manual"
    
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

@router.delete("/leads/{lead_id}", dependencies=[Depends(RoleChecker(["admin"]))])
async def delete_lead(lead_id: int, session: Session = Depends(get_session)):
    """Delete a lead."""
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    session.delete(db_lead)
    session.commit()
    return {"message": "Lead deleted"}

@router.put("/leads/{lead_id}", response_model=Lead)
async def update_lead(lead_id: int, lead: LeadCreate, session: Session = Depends(get_session)):
    """Update a lead."""
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    
    lead_data = lead.dict(exclude_unset=True)
    for key, value in lead_data.items():
        setattr(db_lead, key, value)
        
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

@router.post("/leads/upload")
async def upload_leads(
    file: UploadFile = File(...), 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    contents = await file.read()
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Invalid format")
        
        df.columns = [c.lower().strip() for c in df.columns]
        added = 0
        for _, row in df.iterrows():
            raw_phone = str(row.get("phone", "")).replace(".0", "").strip()
            phone = normalize_phone(raw_phone)
            if phone and not session.exec(select(Lead).where(Lead.phone == phone)).first():
                new_lead = Lead(
                    name=row.get("name", "Unknown"), 
                    phone=phone, 
                    source="Upload",
                    created_by=current_user.username
                )
                session.add(new_lead)
                added += 1
        session.commit()
        return {"message": f"Added {added} leads"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/leads/fetch-apollo", dependencies=[Depends(RoleChecker(["admin"]))])
async def fetch_apollo(search: ApolloSearch, session: Session = Depends(get_session)):
    """Fetches leads from Apollo.io (Organizations) and adds them to DB."""
    if not APOLLO_API_KEY:
        raise HTTPException(status_code=500, detail="APOLLO_API_KEY not configured.")

    url = "https://api.apollo.io/v1/organizations/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": APOLLO_API_KEY
    }
    payload = {
        "q_organization_name": search.keywords,
        "page": 1,
        "per_page": 10 
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        data = response.json()
        
        if response.status_code != 200:
             raise HTTPException(status_code=response.status_code, detail=data.get("error", "Apollo API Error"))

        organizations = data.get("organizations", [])
        leads_added = 0
        
        for org in organizations:
            name = org.get("name")
            phone = org.get("phone_number") or "N/A"
            if not name or phone == "N/A":
                continue

            existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
            if not existing:
                new_lead = Lead(
                    name=name,
                    phone=phone,
                    email=None, 
                    notes=f"Apollo Import: {org.get('primary_domain', '')}",
                    source="Apollo API",
                    status="New"
                )
                session.add(new_lead)
                leads_added += 1
        
        session.commit()
        return {"message": f"Successfully imported {leads_added} leads from Apollo.", "total_found": len(organizations)}
    except Exception as e:
        logger.error(f"Apollo Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/analytics/outcomes", dependencies=[Depends(RoleChecker(["admin"]))])
async def get_outcome_analytics(session: Session = Depends(get_session)):
    """Fetches Pipeline Value and outcome counts by stage."""
    forecast_query = text("SELECT SUM(potential_value * probability) FROM outcome")
    forecasted_revenue = session.exec(forecast_query).one() or 0.0
    
    stage_query = select(Outcome.stage, func.count(Outcome.id), func.sum(Outcome.potential_value * Outcome.probability)).group_by(Outcome.stage)
    results = session.exec(stage_query).all()
    
    funnel_analytics = {}
    for stage, count, weighted_val in results:
        funnel_analytics[stage] = {
            "count": count,
            "weighted_pipeline_value": weighted_val or 0.0
        }
    
    return {
        "forecasted_revenue": forecasted_revenue,
        "funnel_analytics": funnel_analytics,
        "currency": "USD",
        "model": "Probability-Weighted Pipeline"
    }

@router.post("/leads/{lead_id}/enrich")
async def enrich_lead(lead_id: int):
    """Triggers the waterfall enrichment for a specific lead."""
    result = enrich_lead_cascade(lead_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

@router.get("/dashboard/stats", dependencies=[Depends(RoleChecker(["admin"]))])
async def get_dashboard_stats(session: Session = Depends(get_session)):
    """Fetch aggregated stats for the dashboard."""
    total_leads = session.exec(select(func.count(Lead.id))).one()
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    calls_today = session.exec(select(func.count(Interaction.id)).where(Interaction.type == "call").where(Interaction.timestamp >= today_start)).one()
    
    converted = session.exec(select(func.count(Lead.id)).where(Lead.status == "Converted")).one()
    follow_up = session.exec(select(func.count(Lead.id)).where(Lead.status == "Follow-up")).one()
    
    return {
        "total_leads": total_leads,
        "calls_today": calls_today,
        "converted": converted,
        "follow_up": follow_up
    }

@router.get("/interactions")
async def get_interactions(session: Session = Depends(get_session)):
    """Fetch call history."""
    return session.exec(select(Interaction).order_by(Interaction.timestamp.desc())).all()

@router.get("/inventory", response_model=List[Product])
async def get_inventory(session: Session = Depends(get_session)):
    """Fetch all products from inventory."""
    return session.exec(select(Product)).all()

@router.get("/settings")
async def get_settings(session: Session = Depends(get_session)):
    """Fetch all system settings."""
    settings = session.exec(select(SystemSettings)).all()
    return {s.key: s.value for s in settings}

@router.patch("/settings", dependencies=[Depends(RoleChecker(["admin"]))])
async def update_settings(data: dict, session: Session = Depends(get_session)):
    """Update system settings."""
    for key, value in data.items():
        db_s = session.exec(select(SystemSettings).where(SystemSettings.key == key)).first()
        if not db_s:
            db_s = SystemSettings(key=key, value=str(value))
        else:
            db_s.value = str(value)
        session.add(db_s)
    session.commit()
    return {"message": "Settings updated"}
