import logging
import io
import pandas as pd
import requests
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlmodel import Session, select, func, text
from database import get_session, engine
from models.models import Lead, LeadCreate, Product, Interaction, Outcome, ApolloSearch, SystemSettings, User, LatencyLog
from utils.config import get_apollo_api_key
from auth import RoleChecker, get_current_active_user
from enrichment_service import enrich_lead_cascade
from utils.phone import normalize_phone
from utils import settings_cache
from utils.encryption import encrypt_value, decrypt_value

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/crm", tags=["CRM"])

@router.get("/leads")
async def get_leads(
    page: int = 1,
    limit: int = 10,
    session: Session = Depends(get_session)
):
    """Fetch leads from the database with pagination."""
    offset = (page - 1) * limit
    total = session.exec(select(func.count(Lead.id))).one()
    leads = session.exec(
        select(Lead)
        .order_by(Lead.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    
    return {
        "items": leads,
        "total": total,
        "page": page,
        "limit": limit
    }

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
    apollo_api_key = get_apollo_api_key()
    if not apollo_api_key:
        raise HTTPException(status_code=500, detail="Apollo API key not configured. Go to Settings → Credentials.")

    url = "https://api.apollo.io/v1/organizations/search"
    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "no-cache",
        "X-Api-Key": apollo_api_key
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
async def get_interactions(
    page: int = 1,
    limit: int = 10,
    session: Session = Depends(get_session)
):
    """Fetch call history with pagination."""
    offset = (page - 1) * limit
    total = session.exec(select(func.count(Interaction.id))).one()
    
    # Join with Lead to get the name for UI
    statement = (
        select(Interaction, Lead.name.label("lead_name"))
        .outerjoin(Lead, Interaction.lead_id == Lead.id)
        .order_by(Interaction.timestamp.desc())
        .offset(offset)
        .limit(limit)
    )
    results = session.exec(statement).all()
    
    items = []
    for interaction, lead_name in results:
        data = interaction.model_dump()
        data["lead_name"] = lead_name or "Unknown Lead"
        items.append(data)
    
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit
    }

@router.get("/inventory")
async def get_inventory(
    page: int = 1,
    limit: int = 10,
    session: Session = Depends(get_session)
):
    """Fetch items from inventory with pagination."""
    offset = (page - 1) * limit
    total = session.exec(select(func.count(Product.id))).one()
    products = session.exec(
        select(Product)
        .offset(offset)
        .limit(limit)
    ).all()
    
    return {
        "items": products,
        "total": total,
        "page": page,
        "limit": limit
    }

@router.get("/settings")
async def get_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Fetch all system settings for the current user."""
    # First get global settings
    global_settings = session.exec(select(SystemSettings).where(SystemSettings.user_id == None)).all()
    settings_dict = {s.key: s.value for s in global_settings}
    
    # Then overwrite with user-specific settings if they exist
    user_settings = session.exec(select(SystemSettings).where(SystemSettings.user_id == current_user.id)).all()
    for s in user_settings:
        settings_dict[s.key] = s.value
        
    return settings_dict

@router.patch("/settings")
async def update_settings(
    data: dict, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Update system settings for the current user."""
    logger.info(f"💾 [update_settings] User: {current_user.username} (ID: {current_user.id}) | Keys: {list(data.keys())}")
    for key, value in data.items():
        val_str = str(value)
        # Find existing user-specific setting
        db_s = session.exec(
            select(SystemSettings).where(
                SystemSettings.key == key, 
                SystemSettings.user_id == current_user.id
            )
        ).first()
        
        if not db_s:
            logger.info(f"🆕 [update_settings] Creating new user setting: {key}={val_str} for user_id={current_user.id}")
            db_s = SystemSettings(
                key=key, 
                value=val_str, 
                user_id=current_user.id,
                created_by=current_user.username,
                updated_by=current_user.username
            )
            session.add(db_s)
        else:
            if db_s.value != val_str:
                logger.info(f"🔄 [update_settings] Updating user setting: {key} from {db_s.value} to {val_str}")
                db_s.value = val_str
                db_s.updated_by = current_user.username
                session.add(db_s)
            else:
                logger.debug(f"ℹ️ [update_settings] No change for {key}")
            
    session.commit()
    logger.info(f"✅ [update_settings] Successfully committed changes for user {current_user.username}")
    # Update user-specific cache
    settings_cache.update({key: str(value) for key, value in data.items()}, user_id=current_user.id)
    return {"message": "Settings updated"}

@router.get("/integrations/keys")
async def get_integration_keys(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Fetch user's API keys securely (returns masked)."""
    settings = session.exec(
        select(SystemSettings).where(
            SystemSettings.user_id == current_user.id,
            (SystemSettings.key.like("%_API_KEY")) | 
            (SystemSettings.key.like("%_SID")) | 
            (SystemSettings.key.like("%_TOKEN")) |
            (SystemSettings.key.like("%_MODEL")) |
            (SystemSettings.key.like("%_VOICE_ID")) |
            (SystemSettings.key.like("%_VOICE")) | 
            (SystemSettings.key.like("%_STT_MODEL")) |
            (SystemSettings.key.like("%_TTS_MODEL")) |
            (SystemSettings.key.like("SMTP_%")) |
            (SystemSettings.key.in_(["PHONE_NUMBER_FROM", "WHATSAPP_NUMBER_FROM", "EXOPHONE", "EXOTEL_APP_ID", "ENABLEX_APP_ID", "ENABLEX_APP_KEY", "ENABLEX_FROM_NUMBER"]))
        )
    ).all()
    
    # Returns masked representation (e.g. sk-****123)
    masked = {}
    for s in settings:
        decrypted = decrypt_value(s.value)
        if decrypted and len(decrypted) > 8:
            masked[s.key] = decrypted[:3] + "..." + decrypted[-4:]
        elif decrypted:
            masked[s.key] = "***"
        else:
            masked[s.key] = ""
            
    return masked

@router.patch("/integrations/keys")
async def update_integration_keys(
    data: dict, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Securely encrypt and update user integration keys."""
    logger.info(f"🔐 [update_integration_keys] User: {current_user.username} (ID: {current_user.id}) | Keys: {list(data.keys())}")
    for key, value in data.items():
        if not (key.endswith("_API_KEY") or key.endswith("_SID") or key.endswith("_TOKEN") or key.endswith("_MODEL") or key.endswith("_VOICE_ID") or key.endswith("_VOICE") or key.endswith("_STT_MODEL") or key.endswith("_TTS_MODEL") or key.startswith("SMTP_") or key in ["PHONE_NUMBER_FROM", "WHATSAPP_NUMBER_FROM", "EXOPHONE", "EXOTEL_APP_ID", "ENABLEX_APP_ID", "ENABLEX_APP_KEY", "ENABLEX_FROM_NUMBER"]):
             continue # Only handle sensitive keys here
             
        val_str = str(value).strip()
        
        # skip if empty or masked (meaning the user didn't change it or deleted it in UI)
        if not val_str:
            logger.debug(f"⏭️ [update_integration_keys] Skipping empty value for {key}")
            continue
        if val_str.startswith("***") or "..." in val_str:
            logger.debug(f"⏭️ [update_integration_keys] Skipping masked value for {key}")
            continue
            
        encrypted_val = encrypt_value(val_str)
        
        db_s = session.exec(
            select(SystemSettings).where(
                SystemSettings.key == key, 
                SystemSettings.user_id == current_user.id
            )
        ).first()
        
        if not db_s:
            logger.info(f"🆕 [update_integration_keys] Creating new user integration key: {key} for user_id={current_user.id}")
            db_s = SystemSettings(
                key=key, 
                value=encrypted_val, 
                user_id=current_user.id,
                created_by=current_user.username,
                updated_by=current_user.username
            )
            session.add(db_s)
        else:
            if db_s.value != encrypted_val:
                logger.info(f"🔄 [update_integration_keys] Updating user integration key: {key}")
                db_s.value = encrypted_val
                db_s.updated_by = current_user.username
                session.add(db_s)
            
        # Sync cache only for changed keys
        settings_cache.set_val(key, val_str, user_id=current_user.id)
        
    session.commit()
    logger.info(f"✅ [update_integration_keys] Successfully committed integration keys for user {current_user.username}")
    return {"message": "Integration keys updated securely"}

@router.get("/settings/reload_cache", dependencies=[Depends(RoleChecker(["admin"]))])
async def reload_settings_cache(session: Session = Depends(get_session)):
    """Force reload settings from DB into cache."""
    settings_cache.load(session)
    return {"message": f"Settings cache reloaded. Cache reloaded with {len(settings_cache.get_all())} keys"}

@router.post("/inventory", response_model=Product)
async def add_product(
    product: Product, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Smart Upsert: Create if no ID provided, else update existing."""
    if product.id and product.id > 0:
        db_product = session.get(Product, product.id)
        if db_product:
            # Map incoming model to dict and update fields
            product_data = product.model_dump(exclude_unset=True)
            for key, value in product_data.items():
                if key != "id":
                    setattr(db_product, key, value)

            db_product.updated_by = current_user.username
            session.add(db_product)
            session.commit()
            session.refresh(db_product)
            return db_product

    # Create new record if ID is 0, None, or not found
    product.id = None 
    product.created_by = current_user.username
    session.add(product)
    session.commit()
    session.refresh(product)
    return product

@router.put("/inventory/{product_id}", response_model=Product)
async def update_product(
    product_id: int, 
    data: dict, 
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Update an inventory item (Standard REST PUT)."""
    db_product = session.get(Product, product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")
    
    for key, value in data.items():
        if hasattr(db_product, key) and key != "id":
            setattr(db_product, key, value)
            
    db_product.updated_by = current_user.username
    session.add(db_product)
    session.commit()
    session.refresh(db_product)
    return db_product

@router.delete("/inventory/{product_id}")
async def delete_product(
    product_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user)
):
    """Delete an inventory item."""
    db_product = session.get(Product, product_id)
    if not db_product:
        raise HTTPException(status_code=404, detail="Product not found")

    session.delete(db_product)
    session.commit()
    return {"message": "Product deleted successfully"}


# ── Outcome / Pipeline CRUD ───────────────────────────────────────────────────

class OutcomeUpdate(BaseModel):
    stage: Optional[str] = None
    potential_value: Optional[float] = None
    probability: Optional[float] = None
    notes: Optional[str] = None

    class Config:
        # Allow None fields to be excluded from partial updates
        extra = "ignore"


@router.get("/outcomes", dependencies=[Depends(RoleChecker(["admin"]))])
async def list_outcomes(session: Session = Depends(get_session)):
    """Fetch all pipeline outcomes (admin only)."""
    outcomes = session.exec(select(Outcome).order_by(Outcome.created_at.desc())).all()
    return outcomes


@router.get("/outcomes/lead/{lead_id}")
async def get_outcomes_for_lead(lead_id: int, session: Session = Depends(get_session)):
    """Fetch all outcomes for a specific lead."""
    outcomes = session.exec(
        select(Outcome).where(Outcome.lead_id == lead_id).order_by(Outcome.created_at.desc())
    ).all()
    return outcomes


@router.put("/outcomes/{outcome_id}", dependencies=[Depends(RoleChecker(["admin"]))])
async def update_outcome(
    outcome_id: int,
    data: OutcomeUpdate,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_active_user),
):
    """Update a pipeline outcome's stage, deal value, probability, or notes (admin only)."""
    outcome = session.get(Outcome, outcome_id)
    if not outcome:
        raise HTTPException(status_code=404, detail="Outcome not found")

    update_data = data.dict(exclude_unset=True)
    for key, value in update_data.items():
        setattr(outcome, key, value)

    outcome.updated_by = current_user.username
    session.add(outcome)
    session.commit()
    session.refresh(outcome)
    return outcome


@router.delete("/outcomes/{outcome_id}", dependencies=[Depends(RoleChecker(["admin"]))])
async def delete_outcome(outcome_id: int, session: Session = Depends(get_session)):
    """Delete a pipeline outcome (admin only)."""
    outcome = session.get(Outcome, outcome_id)
    if not outcome:
        raise HTTPException(status_code=404, detail="Outcome not found")

    session.delete(outcome)
    session.commit()
    return {"message": "Outcome deleted successfully"}