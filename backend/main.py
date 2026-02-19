import os
import random
import json
import asyncio
import base64
import sys
import uuid
import audioop
import re
import pandas as pd
import io
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, WebSocket, Request, HTTPException, Depends, WebSocketDisconnect, UploadFile, File, status
from fastapi.responses import HTMLResponse, JSONResponse
from twilio.twiml.voice_response import VoiceResponse, Connect
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
from dotenv import load_dotenv
import requests
from google import genai
from google.genai import types
from mistralai import Mistral as MistralClient

# ENHANCED LOGGING SETUP

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - [%(levelname)s] [%(name)s] %(message)s'
)
logger = logging.getLogger(__name__)
try:
    from deepgram import DeepgramClient
    # v5 SDK locations
    from deepgram.listen.live.v1 import LiveOptions
    try:
        from deepgram import LiveTranscriptionEvents
    except Exception:
        LiveTranscriptionEvents = None
except ImportError:
    try:
        from deepgram import DeepgramClient
        # Older SDKs
        from deepgram.options import LiveOptions
        try:
            from deepgram import LiveTranscriptionEvents
        except Exception:
            LiveTranscriptionEvents = None
    except ImportError:
        DeepgramClient = globals().get('DeepgramClient')
        LiveOptions = None
        LiveTranscriptionEvents = None
import aiohttp
from database import (
    init_db, get_session, Lead, LeadCreate, engine, Interaction, 
    Product, SystemSettings, Appointment, Outcome, User, UserCreate
)
from sqlmodel import Session, select, func, text, col, SQLModel
from rag_service import search_knowledge_base
from enrichment_service import enrich_lead_cascade
from email_service import send_smtp_email, get_styled_html
from tool_adapter import get_mistral_tools, execute_mcp_tool
from fastapi.security import OAuth2PasswordRequestForm
from auth import (
    Token, get_current_user, get_current_active_user, create_access_token, 
    get_password_hash, verify_password, ACCESS_TOKEN_EXPIRE_MINUTES,
    RoleChecker, generate_mfa_secret, verify_mfa_token, 
    get_mfa_provisioning_uri, generate_mfa_qr_base64
)

# Initialize DB on startup
init_db()

from fastapi.middleware.cors import CORSMiddleware

# RIO PERSONA & SYSTEM PROMPT (2026 RACE Framework)

RIO_PERSONA_PROMPT = """
You are Rio, a Senior Sales Consultant at [Your Company]. You are NOT a bot; you are a professional sales representative.

**ROLE**: Senior Sales Consultant
- Your tone is professional, empathetic, and knowledgeable.
- You are speaking to a prospect who called or was called regarding [Product/Service].
- Your goal is to qualify them and schedule a demo if they are a good fit.

**CONTEXT**: 
- Use BANT framework to qualify: Budget, Authority, Need, Timeline
- Always prioritize understanding the prospect's pain points before offering solutions.
- If you don't know something, be honest—don't make up information.

**CRITICAL GUARDRAILS** (You MUST follow these):
1. **Pricing**: ALWAYS use the `get_product_info()` tool before quoting any price. Never hallucinate prices.
2. **Discounts**: NEVER offer discounts >10% without using `check_guardrails()` tool first. If >10%, tell prospect manager approval is needed.
3. **ICP Check**: Use `check_icp_qualification()` early in call to determine if prospect meets our Ideal Customer Profile.
4. **Booking**: Only call `book_meeting()` AFTER prospect confirms they want a demo and agrees to a time.

**TASK - BANT QUALIFICATION SEQUENCE**:
1. **NEED**: "What challenges are you currently facing? What would a solution look like for you?"
2. **AUTHORITY**: "Are you the primary decision-maker, or will others be involved in this decision?"
3. **TIMELINE**: "When are you looking to implement a solution? This year? Next quarter?"
4. **BUDGET**: "Does your team have a budget allocated for this category?"

**ACTION BASED ON RESULTS**:
- ✓ If QUALIFIED (meets ICP + positive BANT): "I'd love to show you a demo tailored to your needs. How does [day/time] work?"
- ✗ If NOT QUALIFIED (doesn't meet ICP or BANT incomplete): "Thank you for your time. A specialist will follow up with resources via email that may help."

**RESPONSE BEHAVIOR**:
- Speak naturally—use contractions, short sentences, natural pauses.
- Listen more than you talk. Ask follow-up questions based on prospect responses.
- Show empathy: "That sounds like a real challenge. Many of our customers faced the same issue."
- Be direct: Get to the point; respect prospect's time.

**DO NOT** (Strict Rules):
- Do NOT offer pricing without `get_product_info()` tool.
- Do NOT promise discounts without `check_guardrails()` tool.
- Do NOT book a demo without explicit prospect agreement.
"""

app = FastAPI()

@app.post("/token", response_model=Token)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(), 
    mfa_token: Optional[str] = None, # Optional mfa token
    session: Session = Depends(get_session)
):
    user = session.exec(select(User).where(User.username == form_data.username)).first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    print(f"DEBUG: Login attempt for user: {user.username}")
    print(f"DEBUG: User Status - Email Verified: {user.email_verified}, MFA Enabled: {user.mfa_enabled}")
    
    if not user.email_verified:
         print("DEBUG: Login failed - EMAIL_UNVERIFIED")
         raise HTTPException(
             status_code=status.HTTP_403_FORBIDDEN,
             detail="EMAIL_UNVERIFIED"
         )
    
    # MFA Logic
    if user.mfa_enabled:
        print(f"DEBUG: MFA is enabled for {user.username}. MFA Token provided: {bool(mfa_token)}")
        if not mfa_token:
             print("DEBUG: Login failed - MFA_REQUIRED")
             return JSONResponse(status_code=403, content={"detail": "MFA_REQUIRED"})
        if not verify_mfa_token(user.mfa_secret, mfa_token):
             print("DEBUG: Login failed - Invalid MFA token")
             raise HTTPException(status_code=401, detail="Invalid MFA token")
    
    print(f"DEBUG: Login successful for {user.username}")

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/mfa/setup")
async def setup_mfa(current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    """Generate MFA secret and QR code for the user."""
    if current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA already enabled")
    
    secret = generate_mfa_secret()
    current_user.mfa_secret = secret
    session.add(current_user)
    session.commit()
    
    uri = get_mfa_provisioning_uri(current_user.username, secret)
    qr_code = generate_mfa_qr_base64(uri)
    
    return {"secret": secret, "qr_code": qr_code}

class MFAVerify(SQLModel):
    token: str

@app.post("/auth/mfa/enable")
async def enable_mfa(verify: MFAVerify, current_user: User = Depends(get_current_active_user), session: Session = Depends(get_session)):
    """Verify first token and enable MFA."""
    if not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA not set up")
    
    if verify_mfa_token(current_user.mfa_secret, verify.token):
        current_user.mfa_enabled = True
        session.add(current_user)
        session.commit()

        # Send Confirmation Email
        subject = "Rio CRM: Two-Factor Authentication Enabled"
        email_body = f"Hello {current_user.username},\n\nTwo-Factor Authentication (2FA) has been successfully enabled on your account. Your account is now more secure."
        styled_html = get_styled_html(
            "MFA Enabled Successfully",
            "Your account is now protected with 2FA.<br><br>You will be required to enter a code from your authenticator app every time you log in.",
            current_user.username
        )
        send_smtp_email(current_user.email, subject, email_body, styled_html)

        return {"message": "MFA enabled successfully"}

@app.post("/auth/mfa/request-disable")
async def request_mfa_disable(
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """Generates and emails an OTP to disable MFA."""
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    
    otp = "".join([str(random.randint(0, 9)) for _ in range(6)])
    current_user.mfa_disable_otp = otp
    session.add(current_user)
    session.commit()

    # Send OTP via Email
    subject = "Rio CRM: OTP to disable Two-Factor Authentication"
    email_body = f"Hello {current_user.username},\n\nYour OTP to disable Two-Factor Authentication is: {otp}\n\nIf you did not request this, please change your password immediately."
    styled_html = get_styled_html(
        "MFA Disable OTP",
        f"You have requested to disable 2FA on your account. Your verification code is:<br><br><span style='font-size: 24px; font-weight: bold; color: #7c3aed; letter-spacing: 5px;'>{otp}</span><br><br>If you did not request this, please ignore this email.",
        current_user.username
    )
    
    send_smtp_email(current_user.email, subject, email_body, styled_html)
    
    return {"message": "OTP sent to your registered email"}

class MFADisableRequest(SQLModel):
    token: str

@app.post("/auth/mfa/disable")
async def verify_mfa_disable(
    request: MFADisableRequest,
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """Verifies the email OTP and disables MFA."""
    if not current_user.mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")
    
    if not current_user.mfa_disable_otp or request.token != current_user.mfa_disable_otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")
    
    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_disable_otp = None
    session.add(current_user)
    session.commit()

    # Send Confirmation Email
    subject = "Rio CRM: Two-Factor Authentication Disabled"
    email_body = f"Hello {current_user.username},\n\nTwo-Factor Authentication (2FA) has been successfully disabled on your account as per your request."
    styled_html = get_styled_html(
        "MFA Disabled Successfully",
        "Two-Factor Authentication has been removed from your account.<br><br>If you did not request this, please secure your account immediately.",
        current_user.username
    )
    send_smtp_email(current_user.email, subject, email_body, styled_html)
    
    return {"message": "MFA disabled successfully"}
@app.delete("/auth/me")
async def delete_my_account(
    current_user: User = Depends(get_current_active_user),
    session: Session = Depends(get_session)
):
    """Securely delete the currently authenticated user's account and send a notification."""
    user_email = current_user.email
    user_name = current_user.username
    user_role = current_user.role

    # Send Confirmation Email
    subject = "Your Rio CRM Account has been Deleted"
    email_body = f"Hello {user_name},\n\nYour account (Role: {user_role}) has been successfully deleted from Rio CRM as per your request.\n\nIf this was a mistake, please contact support immediately."
    styled_html = get_styled_html(
        subject, 
        f"Your account with the role <strong>{user_role}</strong> has been successfully removed from our system.<br><br>We're sorry to see you go!", 
        user_name
    )
    
    send_smtp_email(user_email, subject, email_body, styled_html)

    session.delete(current_user)
    session.commit()
    return {"message": "Account successfully deleted and confirmation email sent"}

@app.post("/register", response_model=User)
async def register_user(user: UserCreate, session: Session = Depends(get_session)):
    existing_user_name = session.exec(select(User).where(User.username == user.username)).first()
    if existing_user_name:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    existing_user_email = session.exec(select(User).where(User.email == user.email)).first()
    if existing_user_email:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    verification_token = str(uuid.uuid4())
    db_user = User(
        username=user.username,
        email=user.email,
        hashed_password=get_password_hash(user.password),
        is_active=True,
        email_verified=False,
        verification_token=verification_token
    )
    session.add(db_user)
    session.commit()
    session.refresh(db_user)

    # Send Verification Email
    verify_link = f"http://localhost:3006/verify?token={verification_token}"
    email_body = f"Welcome to Rio CRM! Please verify your email by clicking the link below:\n\n{verify_link}"
    styled_html = get_styled_html("Verify Your Email", f"Please click the button below to verify your account and get started with Rio CRM.<br><br><a href='{verify_link}' class='btn' style='color: white;'>Verify Email</a>", db_user.username)
    
    send_smtp_email(db_user.email, "Verify Your Rio CRM Account", email_body, styled_html)

    return db_user

@app.get("/verify")
async def verify_email(token: str, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.verification_token == token)).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid or expired verification token")
    
    user.email_verified = True
    user.verification_token = None # Clear token after use
    session.add(user)
    session.commit()
    return {"message": "Email verified successfully. You can now log in."}

class ResendVerification(SQLModel):
    email: Optional[str] = None
    username: Optional[str] = None

@app.post("/auth/resend-verification")
async def resend_verification(data: ResendVerification, session: Session = Depends(get_session)):
    user = None
    if data.email:
        user = session.exec(select(User).where(User.email == data.email)).first()
    elif data.username:
        user = session.exec(select(User).where(User.username == data.username)).first()
    
    if not user:
        return {"message": "If the account exists, a new link has been sent."}
    
    if user.email_verified:
        return {"message": "Email is already verified."}
    
    # Generate new token
    verification_token = str(uuid.uuid4())
    user.verification_token = verification_token
    session.add(user)
    session.commit()

    # Send Email
    verify_link = f"http://localhost:3006/verify?token={verification_token}"
    email_body = f"Click here to verify your account: {verify_link}"
    styled_html = get_styled_html("Verify Your Email", f"You requested a new verification link. Please click below to confirm your account.<br><br><a href='{verify_link}' class='btn' style='color: white;'>Verify Email</a>", user.username)
    
    send_smtp_email(user.email, "New Verification Link - Rio CRM", email_body, styled_html)
    
    return {"message": "New verification link sent."}

@app.get("/users/me", response_model=User)
async def read_users_me(current_user: User = Depends(get_current_active_user)):
    return current_user

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3006",
        "http://127.0.0.1:3006"
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CRM API Endpoints
@app.get("/leads", response_model=list[Lead])
async def get_leads(session: Session = Depends(get_session)):
    """Fetch all leads from the database."""
    leads = session.exec(select(Lead).order_by(Lead.created_at.desc())).all()
    return leads

@app.post("/leads", response_model=Lead)
async def create_lead(lead: LeadCreate, session: Session = Depends(get_session)):
    """Create a new lead."""
    db_lead = Lead.model_validate(lead)
    session.add(db_lead)
    session.commit()
    session.refresh(db_lead)
    return db_lead

@app.delete("/leads/{lead_id}", dependencies=[Depends(RoleChecker(["admin"]))])
async def delete_lead(lead_id: int, session: Session = Depends(get_session)):
    """Delete a lead."""
    db_lead = session.get(Lead, lead_id)
    if not db_lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    session.delete(db_lead)
    session.commit()
    return {"message": "Lead deleted"}

@app.put("/leads/{lead_id}", response_model=Lead)
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

class ApolloSearch(SQLModel):
    keywords: str

@app.post("/leads/fetch-apollo", dependencies=[Depends(RoleChecker(["admin"]))])
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
            # Map Organization to Lead
            # Name -> Name, Phone -> Phone
            name = org.get("name")
            phone = org.get("phone_number") or "N/A" # Many orgs might miss phone
            
            if not name or phone == "N/A":
                continue

            # Basic Duplicate Check
            existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
            if not existing:
                new_lead = Lead(
                    name=name,
                    phone=phone,
                    email=None, 
                    # Store domain in notes for now
                    notes=f"Apollo Import: {org.get('primary_domain', '')}",
                    source="Apollo API",
                    status="New"
                )
                session.add(new_lead)
                leads_added += 1
        
        session.commit()
        return {"message": f"Successfully imported {leads_added} leads from Apollo.", "total_found": len(organizations)}

    except Exception as e:
        print(f"Apollo Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/analytics/outcomes", dependencies=[Depends(RoleChecker(["admin"]))])
async def get_outcome_analytics(session: Session = Depends(get_session)):
    """Fetches Pipeline Value and outcome counts by stage."""
    # Forecasted Revenue (Weighted Pipeline)
    # Sum of (Potential Value * Probability)
    forecast_query = text("SELECT SUM(potential_value * probability) FROM outcome")
    forecasted_revenue = session.exec(forecast_query).one() or 0.0
    
    # Outcomes by Stage
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

@app.post("/leads/{lead_id}/enrich")
async def enrich_lead(lead_id: int):
    """Triggers the waterfall enrichment for a specific lead."""
    result = enrich_lead_cascade(lead_id)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result

# Dashboard Stats Endpoint
@app.get("/dashboard/stats", dependencies=[Depends(RoleChecker(["admin"]))])
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

@app.get("/interactions")
async def get_interactions(session: Session = Depends(get_session)):
    """Fetch call history."""
    interactions = session.exec(select(Interaction).order_by(Interaction.timestamp.desc())).all()
    return interactions

# AI Instructions and Configuration are now loaded dynamically from the database.
# Check SystemSettings model in database.py.

# Configuration
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
PHONE_NUMBER_FROM = os.getenv("PHONE_NUMBER_FROM")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "CwhOLp6mAE7h9asvUURR")
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
APOLLO_API_KEY = os.getenv("APOLLO_API_KEY")
CARTESIA_API_KEY = os.getenv("Cartesia_API_Key")
SARVAM_API_KEY = os.getenv("Sarvam_API_Key")

# EnableX Configuration
ENABLEX_APP_ID = os.getenv("EnableX_App_ID")
ENABLEX_APP_KEY = os.getenv("EnableX_App_Key")
ENABLEX_FROM_NUMBER = os.getenv("ENABLEX_FROM_NUMBER")

DOMAIN = os.getenv("DOMAIN")
if DOMAIN:
    DOMAIN = DOMAIN.replace("http://", "").replace("https://", "").replace("/", "")
PORT = int(os.getenv("PORT", 6060))

def check_inventory(product_name: str):
    """
    Checks the stock status and price of a product in the warehouse from the database.
    """
    print(f"Tool Triggered: check_inventory({product_name})")
    
    with Session(engine) as session:
        # Simple ilike or substring search
        search_term = f"%{product_name.lower()}%"
        statement = select(Product).where(col(Product.name).ilike(search_term))
        product = session.exec(statement).first()
        
        if product:
            return json.dumps({
                "product": product.name,
                "stock": product.stock,
                "price": product.price,
                "note": product.note or ""
            })
            
        # If not found, suggest available categories or items
        all_products = session.exec(select(Product.name)).all()
        return json.dumps({
            "product": product_name, 
            "status": "Not found in catalog", 
            "available_items": all_products[:10] # limit to 10 for voice brevity
        })

def query_knowledge_base(query: str):
    """
    Searches the knowledge base for policies, warranty info, and general support questions.
    
    Args:
        query: The user's question or search term (e.g., 'What is the warranty on VRF?', 'Return policy').
    
    Returns:
        String containing relevant context/documents.
    """
    print(f"Tool Triggered: query_knowledge_base({query})")
    results = search_knowledge_base(query)
    if results:
        return f"Context found: {results}"
    if results:
        return f"Context found: {results}"
    return "No relevant info found in knowledge base."

# Lead tool implementation
from database import engine 

def update_lead_tool(phone: str, notes: str, status: str = None):
    """
    Updates the CRM lead information for the given phone number.
    """
    print(f"Tool Triggered: update_lead_tool({phone})")
    with Session(engine) as session:
        statement = select(Lead).where(Lead.phone == phone)
        lead = session.exec(statement).first()
        
        if lead:
            if notes:
                lead.notes = (lead.notes or "") + f"\n[AI]: {notes}"
            if status:
                lead.status = status
            session.add(lead)
            session.commit()
            return f"Updated lead {lead.name}."
        else:
             # Create new lead if not exists? For now just report.
            return "Lead not found for this number."

def send_email_tool(phone: str, email: str, subject: str, body: str):
    """
    Sends an email to the lead. Update lead's email if provided.
    """
    print(f"Tool Triggered: send_email_tool({phone}, {email})")
    with Session(engine) as session:
        statement = select(Lead).where(Lead.phone == phone)
        lead = session.exec(statement).first()
        
        # Priority: use provided email, fallback to DB
        target_email = email or (lead.email if lead else None)
        
        if not target_email:
            return "Error: No email address available for this lead. Please ask the user for their email."

        # Update lead in DB if email was captured on call
        if lead and email and lead.email != email:
            lead.email = email
            lead.notes = (lead.notes or "") + f"\n[AI]: Captured email address: {email}"
            session.add(lead)
            session.commit()
            print(f"Updated lead {lead.name} with email {email}")

        # Generate Premium HTML
        html_content = get_styled_html(subject, body, lead.name if lead else "Valued Customer")
        success = send_smtp_email(target_email, subject, body, html_body=html_content)
        
        if success:
            # Log as interaction
            interaction = Interaction(
                lead_id=lead.id if lead else 0,
                type="email",
                content=f"Sent Email: {subject}",
                timestamp=datetime.now(timezone.utc)
            )
            session.add(interaction)

            # Record Outcome (Pipeline) - Stage: Interest
            outcome = Outcome(
                lead_id=lead.id if lead else 0,
                type="EMAIL_SENT",
                stage="Interest",
                potential_value=1000.0, # Target deal size
                probability=0.0 # 0% chance yet
            )
            session.add(outcome)
            
            session.commit()
            return f"Successfully sent email to {target_email}."
        else:
            return "Failed to send email. Ensure SMTP settings are configured in .env."

def book_demo_tool(phone: str, time_str: str, notes: str = None):
    """
    Books a demo/appointment for the lead.
    time_str should be a natural language or ISO time.
    """
    print(f"Tool Triggered: book_demo_tool({phone}, {time_str})")
    with Session(engine) as session:
        statement = select(Lead).where(Lead.phone == phone)
        lead = session.exec(statement).first()
        
        if not lead:
            return "Error: Lead not found for this phone number."

        try:
            # just use now + some logic or the raw string for demo
            appt_time = datetime.now(timezone.utc) # Mocking the parse
            new_appt = Appointment(
                lead_id=lead.id,
                appointment_time=appt_time,
                notes=f"[AI booked for: {time_str}]: {notes or ''}"
            )
            session.add(new_appt)
            
            # Update Lead status
            lead.status = "Follow-up"
            session.add(lead)
            
            # Log interaction
            interaction = Interaction(
                lead_id=lead.id,
                type="appointment",
                content=f"Booked Demo for {time_str}",
                timestamp=datetime.now(timezone.utc)
            )
            session.add(interaction)

            # Record Outcome (Pipeline) - Stage: Qualification
            outcome = Outcome(
                lead_id=lead.id,
                type="DEMO_BOOKED",
                stage="Qualification",
                potential_value=1000.0,
                probability=0.20 # 20% conversion probability
            )
            session.add(outcome)

            session.commit()
            return f"Successfully booked demo for {lead.name} at {time_str}."
        except Exception as e:
            return f"Error booking demo: {str(e)}"

def query_mcp_resource(resource_uri: str):
    """
    Retrieves data from MCP resources using URIs like crm://leads/summary or crm://inventory.
    Use this to browse data dynamically without specific tools.
    """
    print(f"MCP Triggered: query_mcp_resource({resource_uri})")
    with Session(engine) as session:
        if resource_uri == "crm://leads/summary":
            leads = session.exec(select(Lead)).all()
            return [l.model_dump() for l in leads]
        elif resource_uri == "crm://inventory":
            prods = session.exec(select(Product)).all()
            return [p.model_dump() for p in prods]
        elif resource_uri == "crm://appointments":
            appts = session.exec(select(Appointment)).all()
            return [a.model_dump() for a in appts]
        elif resource_uri.startswith("crm://interactions/"):
            try:
                lid = int(resource_uri.split("/")[-1])
                ints = session.exec(select(Interaction).where(Interaction.lead_id == lid).limit(5)).all()
                return [i.model_dump() for i in ints]
            except:
                return "Error: Invalid Lead ID in URI."
        else:
            return f"Error: MCP Resource '{resource_uri}' not found or permission denied."

tools = [check_inventory, query_knowledge_base, update_lead_tool, send_email_tool, book_demo_tool, query_mcp_resource]

# Emergency Safety Numbers just for safety or else Twilio will charge $75 as fine.
BLOCKED_NUMBERS = {"911", "112", "999"}



if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and PHONE_NUMBER_FROM and GEMINI_API_KEY):
    print("Error: Missing environment variables in .env")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
# AI Clients
gemini_client = genai.Client(api_key=GEMINI_API_KEY, http_options={"api_version": "v1alpha"})
mistral_client = MistralClient(api_key=MISTRAL_API_KEY)
deepgram_client = DeepgramClient(api_key=DEEPGRAM_API_KEY) if DeepgramClient else None

from fastapi.middleware.cors import CORSMiddleware

# Enable CORS for Dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", response_class=HTMLResponse)
async def index():
    return "<h1>Twilio + Gemini Voice Agent</h1><p>Server is running.</p>"

@app.post("/make-call")
async def make_call(to: str, lead_id: int = None):
    """Initiates an outbound call to the specified number."""
    if not DOMAIN:
        raise HTTPException(status_code=500, detail="DOMAIN environment variable not set")
    
    # Safety Check
    cleaned_number = to.replace("+", "").strip()
    if cleaned_number in BLOCKED_NUMBERS or to.strip() in BLOCKED_NUMBERS:
        raise HTTPException(status_code=400, detail="Emergency numbers are blocked for safety.")
    
    
    # Get active telephony engine
    with Session(engine) as db_session:
        telephony_setting = db_session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first()
        active_telephony = telephony_setting.value if telephony_setting else "twilio"

    try:
        if active_telephony == "enablex":
            # EnableX Outbound
            print(f"Initiating EnableX Call to: {to}")
            enablex_auth = base64.b64encode(f"{ENABLEX_APP_ID}:{ENABLEX_APP_KEY}".encode()).decode()
            headers = {
                "Authorization": f"Basic {enablex_auth}",
                "Content-Type": "application/json"
            }
            webhook_url = f"https://{DOMAIN}/enablex-event"
            if lead_id:
                 webhook_url += f"?lead_id={lead_id}"

            payload = {
                "name": "Rio-Assistant-Call",
                "from": ENABLEX_FROM_NUMBER if ENABLEX_FROM_NUMBER else "917550131495", 
                "to": to,
                "event_url": webhook_url
            }
            
            async with aiohttp.ClientSession() as http_session:
                async with http_session.post("https://api.enablex.io/voice/v1/call", headers=headers, json=payload) as resp:
                    result = await resp.json()
                    if resp.status not in [200, 201]:
                        raise Exception(f"EnableX API Error: {result}")
                    # Create interaction record for Lead tracking
                    with Session(engine) as db_session:
                        interaction = Interaction(
                            lead_id=lead_id if lead_id else 0,
                            type="call",
                            content="Outbound Call (EnableX)",
                            timestamp=datetime.now(timezone.utc)
                        )
                        db_session.add(interaction)
                        db_session.commit()
                        db_session.refresh(interaction)
                        interaction_id = interaction.id

                    return {"message": "EnableX Call initiated", "voice_id": result.get("voice_id"), "interaction_id": interaction_id}
        else:
            # Twilio Outbound
            webhook_url = f"https://{DOMAIN}/incoming-call"
            if lead_id:
                webhook_url += f"?lead_id={lead_id}"

            call = client.calls.create(
                to=to,
                from_=PHONE_NUMBER_FROM,
                url=webhook_url
            )
            return {"message": "Twilio Call initiated", "call_sid": call.sid}
    except Exception as e:
        print(f"Error making call: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/enablex-event")
async def enablex_event(request: Request, lead_id: int = None):
    """Handles EnableX call lifecycle events."""
    data = await request.json()
    # Log full payload for debugging
    print(f"📞 EnableX Webhook Data: {json.dumps(data)}")
    
    # EnableX uses "state" for call lifecycle events
    event_type = data.get("event") or data.get("state")
    voice_id = data.get("voice_id")
    print(f"📞 EnableX Event Key: {event_type} | Voice ID: {voice_id}")

    if event_type == "connected":
        # Initiation of media stream
        enablex_auth = base64.b64encode(f"{ENABLEX_APP_ID}:{ENABLEX_APP_KEY}".encode()).decode()
        headers = {
            "Authorization": f"Basic {enablex_auth}",
            "Content-Type": "application/json"
        }
        
        # Clean domain for WebSocket (remove https://)
        ws_domain = DOMAIN.replace("https://", "").replace("http://", "")
        stream_payload = {
            "wss_host": f"wss://{ws_domain}/enablex-media-stream?voice_id={voice_id}&lead_id={lead_id}",
            "play_on_connect": True
        }
        async with aiohttp.ClientSession() as session:
            # EnableX uses PUT for starting a stream
            async with session.put(f"https://api.enablex.io/voice/v1/call/{voice_id}/stream", headers=headers, json=stream_payload) as resp:
                print(f"🚀 EnableX Stream Request sent (PUT). Status: {resp.status}")
                
    return {"status": "ok"}

@app.post("/incoming-call")
async def incoming_call(request: Request, lead_id: int = None):
    """Returns TwiML to connect the call to the WebSocket stream."""
    response = VoiceResponse()

    # Create an interaction record
    with Session(engine) as session:
        interaction = Interaction(
            lead_id=lead_id if lead_id else 0, # 0 for unknown
            type="call",
            content="Incoming call",
            timestamp=datetime.now(timezone.utc)
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction) # Get the ID
        # Read active engine from settings to tailor the prompt
        engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
        active_engine = (engine_setting.value if engine_setting else "gemini").strip().lower()

    # Announce based on engine
    if active_engine == "mistral":
        response.say("Connected to AI assistant from Yexis Electronics by Mistral. Please start speaking.")
    elif active_engine == "gemini":
        response.say("Connected to AI assistant from Yexis Electronics by Google. Please start speaking.")
    else:
        response.say("Connected to Yexis Electronics AI assistant. Please start speaking.")
    connect = Connect()
    stream = connect.stream(url=f'wss://{request.url.netloc}/media-stream')
    stream.parameter(name="interaction_id", value=str(interaction.id))
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.post("/send-sms")
async def send_sms(to: str, message: str):
    """Sends an outbound SMS."""
    # Safety Check
    cleaned_number = to.replace("+", "").strip()
    if cleaned_number in BLOCKED_NUMBERS or to.strip() in BLOCKED_NUMBERS:
        raise HTTPException(status_code=400, detail="Emergency numbers are blocked.")

    try:
        msg = client.messages.create(
            to=to,
            from_=PHONE_NUMBER_FROM,
            body=message
        )
        return {"message": "SMS sent", "sid": msg.sid}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/incoming-sms")
async def incoming_sms(request: Request):
    """Handles incoming SMS webhooks from Twilio."""
    form_data = await request.form()
    sender = form_data.get("From")
    body = form_data.get("Body")
    
    print(f"Received SMS from {sender}: {body}")
    
    # Simple Auto-Reply
    response = MessagingResponse()
    response.message(f"Thanks for your message: '{body}'. Gemini Voice Agent received it.")
    
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.post("/leads/upload")
async def upload_leads(file: UploadFile = File(...), session: Session = Depends(get_session)):
    """Uploads an Excel or CSV file of leads."""
    contents = await file.read()
    
    try:
        if file.filename.endswith('.csv'):
            df = pd.read_csv(io.BytesIO(contents))
        elif file.filename.endswith(('.xls', '.xlsx')):
            df = pd.read_excel(io.BytesIO(contents))
        else:
            raise HTTPException(status_code=400, detail="Invalid file format. Please upload .csv or .xlsx")
        
        # Standardize columns (basic mapping)
        df.columns = [c.lower().strip() for c in df.columns]
        
        leads_added = 0
        errors = []
        
        for index, row in df.iterrows():
            try:
                # Basic validation
                name = row.get("name")
                phone = str(row.get("phone", "")).replace(".0", "").strip() 
                email = row.get("email") if "email" in row else None
                notes = row.get("notes") if "notes" in row else None
                
                if not name or not phone:
                    continue
                    
                # Duplicate check
                existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
                if not existing:
                    new_lead = Lead(
                        name=name,
                        phone=phone,
                        email=email,
                        notes=notes,
                        source="Excel Upload",
                        status="New"
                    )
                    session.add(new_lead)
                    leads_added += 1
            except Exception as e:
                errors.append(f"Row {index}: {e}")
                
        session.commit()
        return {"message": f"Successfully added {leads_added} leads.", "errors": errors}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

class ApolloSearch(SQLModel):
    keywords: str

@app.post("/leads/fetch-apollo")
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
            # Map Organization to Lead
            # Name -> Name, Phone -> Phone
            name = org.get("name")
            phone = org.get("phone_number") or "N/A" # Many orgs might miss phone
            
            if not name or phone == "N/A":
                continue

            # Basic Duplicate Check
            existing = session.exec(select(Lead).where(Lead.phone == phone)).first()
            if not existing:
                new_lead = Lead(
                    name=name,
                    phone=phone,
                    email=None,
                    notes=f"Apollo Import: {org.get('primary_domain')}",
                    source="Apollo API",
                    status="New"
                )
                session.add(new_lead)
                leads_added += 1
        
        session.commit()
        return {"message": f"Successfully imported {leads_added} leads from Apollo.", "total_found": len(organizations)}

    except Exception as e:
        print(f"Apollo Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/leads", response_model=list[Lead])
async def get_leads(session: Session = Depends(get_session)):
    """Fetch all leads."""
    return session.exec(select(Lead)).all()

@app.get("/inventory", response_model=list[Product])
async def get_inventory(session: Session = Depends(get_session)):
    """Fetch all products."""
    return session.exec(select(Product)).all()

@app.post("/inventory", response_model=Product, dependencies=[Depends(RoleChecker(["admin"]))])
async def upsert_product(product: Product, session: Session = Depends(get_session)):
    """Add or update a product."""
    if product.id:
        db_p = session.get(Product, product.id)
        if db_p:
            for k, v in product.dict(exclude_unset=True).items():
                setattr(db_p, k, v)
        else:
            db_p = Product.model_validate(product)
    else:
        db_p = Product.model_validate(product)
        
    session.add(db_p)
    session.commit()
    session.refresh(db_p)
    return db_p

@app.delete("/inventory/{product_id}", dependencies=[Depends(RoleChecker(["admin"]))])
async def delete_product(product_id: int, session: Session = Depends(get_session)):
    """Delete a product."""
    db_p = session.get(Product, product_id)
    if not db_p:
        raise HTTPException(status_code=404, detail="Product not found")
    session.delete(db_p)
    session.commit()
    return {"message": "Product deleted"}

@app.on_event("startup")
async def startup_event():
    """Initialize Rio's persona prompt in the database on startup."""
    from sqlmodel import Session
    session = Session(engine)
    try:
        # Check if Rio's system instruction already exists
        existing = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
        if not existing:
            # Initialize with Rio's persona
            db_setting = SystemSettings(key="system_instruction", value=RIO_PERSONA_PROMPT)
            session.add(db_setting)
            session.commit()
            print("✓ Rio's system prompt initialized in database")
        else:
            print("✓ Rio's system prompt already exists in database")
    except Exception as e:
        print(f"⚠️ Startup initialization error: {e}")
    finally:
        session.close()

@app.get("/settings")
async def get_settings(session: Session = Depends(get_session)):
    """Fetch system settings."""
    instruction = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    engine = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    telephony = session.exec(select(SystemSettings).where(SystemSettings.key == "telephony_engine")).first()
    verbosity = session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first()
    return {
        "system_instruction": instruction.value if instruction else "",
        "voice_engine": engine.value if engine else "gemini",
        "telephony_engine": telephony.value if telephony else "twilio",
        "ai_verbosity": verbosity.value if verbosity else "2"
    }

@app.patch("/settings", dependencies=[Depends(RoleChecker(["admin"]))])
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


class TelephonyCommunicator:
    async def receive(self): pass
    async def send_media(self, b64_audio): pass
    async def clear_audio_buffer(self): pass

class TwilioCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = None
    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                yield data
        except Exception:
            yield {"event": "stop"}
    async def send_media(self, b64_audio):
        if self.stream_sid:
            await self.websocket.send_json({"event": "media", "streamSid": self.stream_sid, "media": {"payload": b64_audio}})
    
    async def clear_audio_buffer(self):
        if self.stream_sid:
            logger.info(f"🚫 [Twilio] Clearing audio buffer for StreamSid: {self.stream_sid}")
            await self.websocket.send_json({"event": "clear", "streamSid": self.stream_sid})

class EnableXCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                # EnableX often sends JSON with "data" key as base64
                # We need to verify if it's text or binary. iter_text() works for text.
                print(f"⏬ EnableX WS Received: {message[:100]}...")
                try:
                    data = json.loads(message)
                    # Map to Twilio-like events for minimal pipeline change
                    if "data" in data:
                        yield {"event": "media", "media": {"payload": data["data"]}}
                    elif data.get("event") == "stop" or data.get("state") == "disconnected":
                        yield {"event": "stop"}
                except json.JSONDecodeError:
                    # If it's not JSON, maybe it's raw binary? But iter_text was used.
                    print("⚠️ EnableX WS: Message is not valid JSON")
                    yield {"event": "media", "media": {"payload": base64.b64encode(message.encode()).decode() if isinstance(message, str) else base64.b64encode(message).decode()}}
        except Exception as e:
            print(f"❌ EnableX WS Receive Error: {e}")
            yield {"event": "stop"}
    async def send_media(self, b64_audio):
        # EnableX expects raw binary or JSON with data
        # Verification: EnableX Voice Server Media Stream API docs
        payload = {"event": "media", "data": b64_audio}
        print(f"⏫ EnableX WS Sending Media: {len(b64_audio)} chars")
        await self.websocket.send_json(payload)

    async def clear_audio_buffer(self):
        # EnableX equivalent for clear/flush. 
        # Research needed for specific EnableX clear event if available.
        # For now, we send a stop/clear event if supported.
        payload = {"event": "clear"} 
        print(f"🚫 EnableX WS Clearing Buffer")
        await self.websocket.send_json(payload)

async def gemini_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator):
    """Handles the Native Multimodal Live API logic for Gemini."""
    
    logger.info(f"🤖 [LLM] Selected: GEMINI 2.0 Flash")
    logger.info(f"🤖 [LLM] Interaction ID: {interaction_id}")
    
    model = "models/gemini-2.0-flash-exp"
    config = {
        "response_modalities": ["AUDIO"],
        "system_instruction": types.Content(parts=[types.Part(text=dynamic_instruction)]),
        "speech_config": {
            "voice_config": {"prebuilt_voice_config": {"voice_name": "Puck"}},
        },
        "tools": [check_inventory, query_knowledge_base, update_lead_tool, send_email_tool, book_demo_tool, query_mcp_resource]
    }

    try:
        async with gemini_client.aio.live.connect(model=model, config=config) as gemini_session:
            async def receive_from_telephony():
                nonlocal interaction_id
                downstream_state = None 
                async for data in communicator.receive():
                    if data["event"] == "start":
                        if isinstance(communicator, TwilioCommunicator):
                            communicator.stream_sid = data["start"]["streamSid"]
                            custom_params = data["start"].get("customParameters", {})
                            if not interaction_id: interaction_id = custom_params.get("interaction_id")
                    elif data["event"] == "media":
                        media_payload = data["media"]["payload"]
                        chunk = base64.b64decode(media_payload)
                        pcm_8k = audioop.ulaw2lin(chunk, 2)
                        pcm_16k, downstream_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, downstream_state)
                        await gemini_session.send(input={"data": pcm_16k, "mime_type": "audio/pcm"}, end_of_turn=False)
                    elif data["event"] == "stop":
                        break

            async def send_to_telephony():
                upstream_state = None
                try:
                    async for response in gemini_session.receive():
                        if response.server_content:
                            if response.server_content.interrupted:
                                logger.info("🛑 [Gemini] User interrupted! Clearing telephony buffer.")
                                await communicator.clear_audio_buffer()
                                # Reset upstream state to avoid distortion on next turn
                                upstream_state = None
                                continue

                            if response.server_content.model_turn:
                                for part in response.server_content.model_turn.parts:
                                    if getattr(part, 'function_call', None):
                                        fc = part.function_call
                                        result = await run_tool(fc.name, fc.args, transcript_accumulator, interaction_id)
                                        await gemini_session.send(input=types.LiveClientToolResponse(
                                            function_responses=[types.FunctionResponse(name=fc.name, id=fc.id, response={"result": result})]
                                        ))
                                    
                                    if getattr(part, 'inline_data', None):
                                        audio_data = part.inline_data.data 
                                        pcm_8k, upstream_state = audioop.ratecv(audio_data, 2, 1, 24000, 8000, upstream_state)
                                        mulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                        b64_audio = base64.b64encode(mulaw_8k).decode("utf-8")
                                        await communicator.send_media(b64_audio)
                                    
                                    if getattr(part, 'text', None):
                                        transcript_accumulator.append(f"Rio: {part.text}")
                                        save_transcript(interaction_id, transcript_accumulator)
                except Exception as e:
                    print(f"Telephony Send Error: {e}")

            await asyncio.gather(receive_from_telephony(), send_to_telephony())
    except Exception as e:
        print(f"Gemini Pipeline Error: {e}")

def apply_verbosity_rules(instruction: str, verbosity: str) -> str:
    """Modifies the instruction based on verbosity level."""
    if verbosity == "1": # Ultra-Concise
        return instruction + "\n\n**STRICT BREVITY RULE**: Reply in EXACTLY ONE SHORT SENTENCE OR EVEN ONE WORD IF POSSIBLE. Be extremely brief. For example, if asked for price, just say the price. If asked to confirm, just say 'Done' or 'Confirmed'. No fluff, no filler."
    elif verbosity == "3": # Detailed
        return instruction + "\n\n**VERBOSITY RULE**: Provide detailed and elaborated responses. Explain things thoroughly."
    else: # Balanced (Default/2)
        return instruction + "\n\n**VERBOSITY RULE**: Keep your responses concise (1-3 sentences)."

@app.websocket("/enablex-media-stream")
async def handle_enablex_media_stream(websocket: WebSocket, session: Session = Depends(get_session)):
    """Handles EnableX WebSocket media stream."""
    await websocket.accept()
    voice_id = websocket.query_params.get("voice_id")
    lead_id = websocket.query_params.get("lead_id")
    
    # Find interaction_id for this voice_id/lead_id
    interaction_id = None
    if lead_id:
        with Session(engine) as db_session:
            # Get latest interaction for this lead
            db_i = db_session.exec(select(Interaction).where(Interaction.lead_id == int(lead_id)).order_by(Interaction.timestamp.desc())).first()
            if db_i: interaction_id = db_i.id

    transcript_accumulator = []
    
    settings = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    dynamic_instruction = settings.value if settings else "You are a helpful assistant."
    engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    active_engine = engine_setting.value if engine_setting else "gemini"
    
    verbosity_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first()
    verbosity = verbosity_setting.value if verbosity_setting else "2"
    dynamic_instruction = apply_verbosity_rules(dynamic_instruction, verbosity)
    
    print(f"EnableX connected to media-stream WS | Voice ID: {voice_id} | Interaction: {interaction_id} | Verbosity: {verbosity}")
    
    communicator = EnableXCommunicator(websocket)
    if active_engine.startswith("mistral"):
        await mistral_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator, engine_type=active_engine)
    else:
        await gemini_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator)

def clean_voice_text(text: str, max_chars: int = 300) -> str:
    """Removes markdown and truncates text for voice output."""
    if not text:
        return ""
    
    # Remove markdown bold/italic/headers
    text = re.sub(r'[*#_~`>]', '', text)
    
    # Remove links
    text = re.sub(r'\[.*?\]\(.*?\)', '', text)
    
    # Clean whitespace
    text = " ".join(text.split())
    
    # Truncate
    if len(text) > max_chars:
        text = text[:max_chars].rsplit(' ', 1)[0] + "..."
        
    return text.strip()

async def run_tool(name, args, transcript_accumulator, interaction_id):
    """Shared tool runner - uses unified MCP tools for both Gemini and Mistral."""
    
    logger.info(f"📋 [MCP] Calling tool: {name}")
    logger.debug(f"📋 [MCP] Arguments: {args}")
    
    # Use unified MCP tool executor
    result = await execute_mcp_tool(name, args)
    
    logger.info(f"📋 [MCP] Tool result: {result}")
    
    if isinstance(result, dict) and "error" not in result:
        transcript_accumulator.append(f"[System]: Executed {name} -> Success")
    else:
        transcript_accumulator.append(f"[System]: Executed {name} -> {result}")
    
    save_transcript(interaction_id, transcript_accumulator)
    return result

def save_transcript(interaction_id, transcript_accumulator):
    """Saves transcript to DB."""
    if interaction_id:
        try:
            with Session(engine) as db_session:
                db_i = db_session.get(Interaction, int(interaction_id))
                if db_i:
                    transcript_text = "\n".join(transcript_accumulator)
                    db_i.transcript = transcript_text
                    db_session.add(db_i)
                    db_session.commit()
                    print(f"✅ Transcript saved for Interaction {interaction_id} ({len(transcript_accumulator)} lines, {len(transcript_text)} chars)")
                else:
                    print(f"⚠️ Interaction {interaction_id} not found in DB for transcript saving.")
        except Exception as e:
            print(f"❌ DB Error saving transcript: {e}")
    else:
        print("⚠️ No interaction_id provided to save_transcript")

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket, session: Session = Depends(get_session)):
    """Handles the WebSocket connection and dispatches to the correct voice engine."""
    await websocket.accept()
    

    interaction_id = websocket.query_params.get("interaction_id")
    transcript_accumulator = []
    
    settings = session.exec(select(SystemSettings).where(SystemSettings.key == "system_instruction")).first()
    dynamic_instruction = settings.value if settings else "You are a helpful assistant."
    
    engine_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "voice_engine")).first()
    active_engine = engine_setting.value if engine_setting else "gemini"
    
    verbosity_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "ai_verbosity")).first()
    verbosity = verbosity_setting.value if verbosity_setting else "2"
    dynamic_instruction = apply_verbosity_rules(dynamic_instruction, verbosity)
    
    print(f"Twilio connected to media-stream WS (Engine: {active_engine.upper()}) | Interaction ID: {interaction_id} | Verbosity: {verbosity}")

    if interaction_id:
        try:
            db_interaction = session.get(Interaction, int(interaction_id))
            if db_interaction and db_interaction.lead_id:
                lead = session.get(Lead, db_interaction.lead_id)
                if lead:
                    context_note = f"\n\n**CURRENT CALL CONTEXT**\nSpeak with {lead.name}. Status: {lead.status}. Goal: Update them."
                    dynamic_instruction += context_note
        except Exception as e:
            print(f"Error loading context: {e}")

    communicator = TwilioCommunicator(websocket)
    if active_engine.startswith("mistral"):
        await mistral_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator, engine_type=active_engine)
    else:
        await gemini_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator)

async def mistral_voice_pipeline(communicator, interaction_id, dynamic_instruction, transcript_accumulator, engine_type="mistral"):
    """Orchestrates STT, Mistral (LLM with MCP tools), and TTS based on engine_type."""
    
    
    logger.info(f"🤖 [LLM] Selected: {engine_type.upper()}")
    logger.info(f"🤖 [LLM] Interaction ID: {interaction_id}")
    
    # Use unified MCP tools for Mistral
    mistral_tools = get_mistral_tools()
    logger.debug(f"🤖 [LLM] Mistral tools loaded: {len(mistral_tools)} tools")

    # Safety and brevity controls (aggressive)
    MAX_VOICE_CHARS = int(os.getenv("MAX_VOICE_CHARS", "140"))
    MISTRAL_MAX_TOKENS = int(os.getenv("MISTRAL_MAX_TOKENS", "120"))
    MISTRAL_TEMPERATURE = float(os.getenv("MISTRAL_TEMPERATURE", "0.2"))
    MAX_TTS_SECONDS = int(os.getenv("MAX_TTS_SECONDS", "12"))

    # Barge-in and task handles
    is_rio_speaking = False
    current_tts_task = None
    current_mistral_task = None

    # Encourage minimal/concise replies via system prompt (very aggressive)
    brevity_instruction = (
        "You are Rio, a concise sales assistant. Answer in 1-2 short sentences (max 20-30 words). "
        "Do NOT wander or add unnecessary details. If an action is required, call the appropriate tool instead of explaining how to do it. "
        "Only ask a single clarifying question when necessary. Be polite but terse."
    )

    messages = [
        {"role": "system", "content": brevity_instruction},
        {"role": "system", "content": dynamic_instruction}
    ]

    async def speak(text):
        """Streaming TTS from selected provider to Twilio. Cancellable for barge-in."""
        nonlocal is_rio_speaking, current_tts_task
        if not text or not text.strip():
            return
            
        clean_text = clean_voice_text(text, max_chars=MAX_VOICE_CHARS)
        is_rio_speaking = True
        
        try:
            if engine_type == "mistral-cartesia":
                # CARTESIA TTS (SONIC-3)
                url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}"
                headers = {"Cartesia-Version": "2024-06-10"}
                logger.info(f"🔊 [Cartesia] TTS starting: {clean_text[:60]}...")
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, headers=headers) as c_ws:
                        # Send Preamble / Settings
                        # For Cartesia WS, we send the generation request
                        payload = {
                            "model_id": "sonic-english", # sonic-3 is for experimental versions
                            "transcript": clean_text,
                            "voice": {
                                "mode": "id",
                                "id": "1259b7e3-cb8a-43df-9446-30971a46b8b0"
                            },
                            "output_format": {
                                "container": "raw",
                                "encoding": "mulaw",
                                "sample_rate": 8000
                            },
                            "generation_config": {
                                "speed": "normal",
                                "volume": "normal"
                            },
                            "context_id": interaction_id or str(uuid.uuid4())
                        }
                        await c_ws.send_json(payload)
                        
                        async for message in c_ws:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(message.data)
                                if data.get("audio"):
                                    pcm_16k = base64.b64decode(data["audio"])
                                    pcm_8k, _ = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)
                                    ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                    payload_b64 = base64.b64encode(ulaw_8k).decode("utf-8")
                                    await communicator.send_media(payload_b64)
                                if data.get("done"):
                                    break
                            elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                                break
                                
            elif engine_type == "mistral-sarvam":
                # SARVAM TTS (BULBUL-V3)
                url = "https://api.sarvam.ai/text-to-speech"
                headers = {"api-subscription-key": SARVAM_API_KEY}
                payload = {
                    "inputs": [clean_text],
                    "target_language_code": "en-IN", # Default to English for Sarvam, or detect
                    "speaker": "meera", # Default speaker
                    "pitch": 0,
                    "pace": 1.0,
                    "loudness": 1.5,
                    "speech_sample_rate": 8000,
                    "enable_preprocessing": True,
                    "model": "bulbul:v1"
                }
                logger.info(f"🔊 [Sarvam] TTS starting: {clean_text[:60]}...")
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            audio_b64 = data.get("audios", [None])[0]
                            if audio_b64:
                                # Sarvam returns base64. 
                                # If 8k pcm, convert to mulaw
                                pcm_8k = base64.b64decode(audio_b64)
                                ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                payload_b64 = base64.b64encode(ulaw_8k).decode("utf-8")
                                await communicator.send_media(payload_b64)

            elif engine_type == "mistral-deepgram":
                # Deepgram TTS (Aura)
                tts_url = f"wss://api.deepgram.com/v1/speak?model=aura-asteria-en&encoding=mulaw&sample_rate=8000"
                headers = {
                    "Authorization": f"Token {DEEPGRAM_API_KEY}",
                }
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(tts_url, headers=headers) as dg_ws:
                        # Deepgram Aura handshake: Send initial text block
                        await dg_ws.send_json({"type": "Speak", "text": clean_text})
                        # Signal that we are done sending text
                        await dg_ws.send_json({"type": "Flush"})
                        
                        async for message in dg_ws:
                            if message.type == aiohttp.WSMsgType.BINARY:
                                # Deepgram sends raw mulaw 8k (no decoding/conversion needed)
                                payload_b64 = base64.b64encode(message.data).decode("utf-8")
                                await communicator.send_media(payload_b64)
                            elif message.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(message.data)
                                if data.get("type") == "Flushed":
                                    break
                            elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                                break

            
            else:
                # DEFAULT: ELEVENLABS
                url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_16000"
                logger.info(f"🔊 [ElevenLabs] TTS starting: {clean_text[:60]}...")
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as el_ws:
                        await el_ws.send_json({
                            "text": " ",
                            "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                            "xi_api_key": ELEVENLABS_API_KEY
                        })
                        await el_ws.send_json({"text": clean_text, "try_trigger_generation": True})
                        await el_ws.send_json({"text": ""})
                        
                        async for message in el_ws:
                            if message.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(message.data)
                                if data.get("audio"):
                                    pcm_16k = base64.b64decode(data["audio"])
                                    pcm_8k, _ = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, None)
                                    ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                                    payload_b64 = base64.b64encode(ulaw_8k).decode("utf-8")
                                    await communicator.send_media(payload_b64)
                                if data.get("isFinal"):
                                    break
                            elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                                break
        except asyncio.CancelledError:
            logger.info("TTS playback cancelled.")
            raise
        except Exception as e:
            logger.error(f"TTS Error ({engine_type}): {e}")
        finally:
            is_rio_speaking = False
            current_tts_task = None

    async def process_mistral(user_input):
        nonlocal current_mistral_task, current_tts_task
        print(f"Processing Mistral Input: {user_input}")
        messages.append({"role": "user", "content": user_input})
        try:
            print("Sending request to Mistral...")
            # Run Mistral call as a cancellable task
            start_time = time.time()
            current_mistral_task = asyncio.create_task(
                mistral_client.chat.complete_async(
                    model="mistral-large-latest",
                    messages=messages,
                    tools=mistral_tools,
                    max_tokens=MISTRAL_MAX_TOKENS,
                    temperature=MISTRAL_TEMPERATURE
                )
            )
            response = await current_mistral_task
            elapsed = time.time() - start_time
            logger.info(f"[Mistral] initial generation time: {elapsed:.2f}s")
            print("Mistral response received.")
            current_mistral_task = None

            choice = response.choices[0].message
            if choice.tool_calls:
                # Short filler while tools run
                filler_msg = "One sec, checking that for you."
                # Start filler but do not await (it can be interrupted)
                asyncio.create_task(speak(filler_msg))

                # Mistral requires the assistant message containing tool_calls 
                # to be in the history BEFORE the tool results.
                messages.append(choice)

                for tc in choice.tool_calls:
                    args = json.loads(tc.function.arguments)
                    print(f"Tool Triggered: {tc.function.name}({args})")
                    result = await run_tool(tc.function.name, args, transcript_accumulator, interaction_id)
                    messages.append({
                        "role": "tool",
                        "name": tc.function.name,
                        "content": str(result),
                        "tool_call_id": tc.id
                    })

                print("Sending tool results back to Mistral...")
                # Run final Mistral call as cancellable task
                current_mistral_task = asyncio.create_task(
                    mistral_client.chat.complete_async(
                        model="mistral-large-latest",
                        messages=messages,
                        max_tokens=MISTRAL_MAX_TOKENS,
                        temperature=MISTRAL_TEMPERATURE
                    )
                )
                final_response = await current_mistral_task
                choice = final_response.choices[0].message
                current_mistral_task = None

            if choice.content:
                print(f"Mistral Reply: {choice.content}")
                messages.append({"role": "assistant", "content": choice.content})
                transcript_accumulator.append(f"Rio: {choice.content}")
                save_transcript(interaction_id, transcript_accumulator)

                # Speak using a cancellable task so barge-in can cancel it
                start_tts = time.time()
                current_tts_task = asyncio.create_task(speak(choice.content))
                try:
                    # Enforce an upper limit on speaking time to keep replies short
                    await asyncio.wait_for(current_tts_task, timeout=MAX_TTS_SECONDS)
                    logger.info(f"[TTS] playback time: {time.time() - start_tts:.2f}s")
                except asyncio.TimeoutError:
                    logger.info(f"[TTS] playback timed out after {MAX_TTS_SECONDS}s - cancelling.")
                    current_tts_task.cancel()
                except asyncio.CancelledError:
                    logger.info("TTS cancelled due to barge-in/interrupt.")
                finally:
                    current_tts_task = None
            else:
                print("Mistral returned empty content.")
        except asyncio.CancelledError:
            print("Mistral generation cancelled (barge-in).")
            current_mistral_task = None
        except Exception as e:
            print(f"Mistral API Error detailed: {e}")
            import traceback
            traceback.print_exc()

    # --- STT IMPLEMENTATION ---
    stt_url = ""
    stt_headers = {}
    
    if engine_type == "mistral-cartesia":
        stt_url = f"wss://api.cartesia.ai/stt/websocket?api_key={CARTESIA_API_KEY}"
        stt_headers = {
            "Cartesia-Version": "2024-06-10"
        }
    elif engine_type == "mistral-sarvam":
        # Use query params for key as well to avoid handshake rejection
        stt_url = f"wss://api.sarvam.ai/speech-to-text-translate/ws?model=saaras:v3&sample_rate=16000&language_code=hi-IN&mode=transcribe&api-subscription-key={SARVAM_API_KEY}"
        stt_headers = {
            "api-subscription-key": SARVAM_API_KEY,
            "Origin": "https://api.sarvam.ai"
        }
    else:
        # Default: DEEPGRAM
        stt_url = "wss://api.deepgram.com/v1/listen?model=nova-2&encoding=mulaw&sample_rate=8000"
        stt_headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(stt_url, headers=stt_headers) as stt_ws:
            
            # Initialization for certain providers
            if engine_type == "mistral-cartesia":
                await stt_ws.send_json({
                    "model": "ink-whisper-2025-06-04",
                    "language": "en",
                    "encoding": "pcm_s16le",
                    "sample_rate": 16000
                })
            # Sarvam parameters are in the URL query string

            async def sender():
                nonlocal interaction_id
                downstream_state = None
                try:
                    async for data in communicator.receive():
                        if data["event"] == "start":
                            if isinstance(communicator, TwilioCommunicator):
                                communicator.stream_sid = data["start"]["streamSid"]
                                if not interaction_id: interaction_id = data["start"].get("customParameters", {}).get("interaction_id")
                            logger.info(f"STT Sender: Stream Started | Interaction: {interaction_id}")
                        elif data["event"] == "media":
                            media_payload = data["media"]["payload"]
                            raw_audio = base64.b64decode(media_payload)
                            
                            if engine_type == "mistral-cartesia":
                                # Convert mulaw 8k to pcm 16k for Cartesia
                                pcm_8k = audioop.ulaw2lin(raw_audio, 2)
                                pcm_16k, downstream_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, downstream_state)
                                await stt_ws.send_bytes(pcm_16k)
                            elif engine_type == "mistral-sarvam":
                                # Sarvam expects JSON with base64 PCM 16k
                                pcm_8k = audioop.ulaw2lin(raw_audio, 2)
                                pcm_16k, downstream_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, downstream_state)
                                b64_audio = base64.b64encode(pcm_16k).decode("utf-8")
                                await stt_ws.send_json({"type": "audio", "data": b64_audio})
                            else:
                                # Deepgram (configured for 8k) takes mulaw or raw
                                await stt_ws.send_bytes(raw_audio)
                        elif data["event"] == "stop":
                            break
                except Exception as e:
                    logger.error(f"STT Sender Error: {e}")
                finally:
                    await stt_ws.close()

            async def receiver():
                try:
                    async for msg in stt_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            res = json.loads(msg.data)
                            transcript = ""
                            is_final = False

                            if engine_type == "mistral-cartesia":
                                transcript = res.get("transcript", "")
                                is_final = res.get("is_final", False)
                            elif engine_type == "mistral-sarvam":
                                # Sarvam returns 'transcript' field for final results
                                transcript = res.get("transcript", "")
                                # In Saaras:v3, if type is 'transcript' or it's a final update
                                is_final = bool(transcript.strip()) and (res.get("type") == "transcript" or res.get("is_final", False))
                            else:
                                # Deepgram
                                if "channel" in res:
                                    alt = res["channel"]["alternatives"][0]
                                    transcript = alt.get("transcript", "")
                                    is_final = res.get("is_final", False)

                            if transcript and is_final:
                                logger.info(f"🎤 [STT] FINAL: {transcript}")
                                
                                # BARGE-IN DETECTION
                                if is_rio_speaking:
                                    logger.info("🛑 Barge-in! Interrupting Rio.")
                                    await communicator.clear_audio_buffer()
                                    if current_tts_task and not current_tts_task.done():
                                        current_tts_task.cancel()
                                    if current_mistral_task and not current_mistral_task.done():
                                        current_mistral_task.cancel()
                                
                                transcript_accumulator.append(f"User: {transcript}")
                                save_transcript(interaction_id, transcript_accumulator)
                                await process_mistral(transcript)
                        elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                            break
                except Exception as e:
                    logger.error(f"STT Receiver Error: {e}")

            await asyncio.gather(sender(), receiver())
    
    print("Mistral pipeline closed.")

if __name__ == "__main__":
    import uvicorn
    # Twilio does not support WebSocket Ping/Pong, so we must disable it in Uvicorn to prevent "keepalive ping timeout" errors.
    uvicorn.run(app, host="0.0.0.0", port=PORT, ws_ping_interval=None, ws_ping_timeout=None, timeout_keep_alive=60)
