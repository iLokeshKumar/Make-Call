import os
import logging
from datetime import datetime, timezone
import re
from dateutil import parser as date_parser
import dateparser
from utils.date_normalizer import normalize_date_ai
from fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from sqlmodel import select
from models.models import Lead, Interaction, Product, Appointment, LatencyLog, Outcome, Demo, User
from rag_service import search_products, sync_products_to_chroma
from utils.phone import normalize_phone

load_dotenv()

# Logger
logger = logging.getLogger(__name__)

# MCP Server
mcp = FastMCP("Rio CRM Navigator")

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Import email service for MCP tool use
try:
    from email_service import send_smtp_email, get_styled_html
    EMAIL_SERVICE_AVAILABLE = True
except ImportError:
    EMAIL_SERVICE_AVAILABLE = False
    logger.warning("Email service not available")

# Import WhatsApp service
try:
    from whatsapp_service import send_whatsapp_message
    WHATSAPP_SERVICE_AVAILABLE = True
except ImportError:
    WHATSAPP_SERVICE_AVAILABLE = False
    logger.warning("WhatsApp service not available")

# Import Google Calendar service for Meet link generation
try:
    from google_calendar_service import create_google_meet_for_booking
    GOOGLE_CALENDAR_AVAILABLE = True
except ImportError:
    GOOGLE_CALENDAR_AVAILABLE = False
    logger.warning("Google Calendar service not available - Meet links will not be generated")

@mcp.resource("crm://leads/summary")
def get_leads_summary():
    """Returns a summary of all leads in the system."""
    with SessionLocal() as session:
        result = session.execute(text("SELECT id, name, phone, status, enrichment_status FROM lead"))
        leads = [dict(row._mapping) for row in result]
        return leads

@mcp.resource("crm://inventory")
def get_inventory():
    """Returns the current product inventory and stock levels."""
    with SessionLocal() as session:
        result = session.execute(text("SELECT name, stock, price, note FROM product"))
        products = [dict(row._mapping) for row in result]
        return products

@mcp.resource("crm://interactions/{lead_id}")
def get_lead_interactions(lead_id: int):
    """Returns the recent call and email history for a specific lead."""
    with SessionLocal() as session:
        result = session.execute(text("SELECT type, content, timestamp FROM interaction WHERE lead_id = :lid ORDER BY timestamp DESC LIMIT 10"), {"lid": lead_id})
        interactions = [dict(row._mapping) for row in result]
        return interactions

@mcp.resource("crm://appointments")
def get_appointments():
    """Returns all scheduled demos and meetings."""
    with SessionLocal() as session:
        result = session.execute(text("SELECT a.appointment_time, l.name as lead_name, a.status FROM appointment a JOIN lead l ON a.lead_id = l.id"))
        appts = [dict(row._mapping) for row in result]
        return appts

@mcp.tool()
def get_or_create_lead(name: str, phone: str, email: str = None) -> dict:
    """
    Looks up a lead by phone number or email, or creates a new one if not found.
    Implements deduplication by checking both identifiers.
    """
    normalized_phone = normalize_phone(phone)
    logger.info(f"[get_or_create_lead] Searching for phone: {normalized_phone} or email: {email}")
    
    with SessionLocal() as session:
        # 1. Search by phone
        lead = session.execute(select(Lead).where(Lead.phone == normalized_phone)).scalars().first()
        
        # 2. Search by email if not found by phone
        if not lead and email:
            lead = session.execute(select(Lead).where(Lead.email == email)).scalars().first()
            if lead:
                logger.info(f"[get_or_create_lead] Found lead by email: {email}")
                # Update phone if it was missing or different?
                # User says: if phone number is different & not present in existing record then create?
                # No, "if lead is already there lets not create a lead". 
                # So if we find it by email, we should probably update the phone if it's new.
                if not lead.phone or lead.phone == "N/A":
                    lead.phone = normalized_phone
                    session.add(lead)
                    session.commit()
                    logger.info(f"[get_or_create_lead] Updated phone for lead {lead.id}")

        if not lead:
            logger.info(f"[get_or_create_lead] Creating new lead: {name}")
            lead = Lead(
                name=name, 
                phone=normalized_phone, 
                email=email, 
                status="New",
                source="On Call",
                created_by="Rio AI"
            )
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return {"lead_id": lead.id, "name": lead.name, "status": "New", "message": "New lead created from call."}
        
        # 3. Update missing info on existing lead
        updated = False
        if email and not lead.email:
            lead.email = email
            updated = True
        
        if normalized_phone and (not lead.phone or lead.phone == "N/A"):
            lead.phone = normalized_phone
            updated = True
            
        if updated:
            session.add(lead)
            session.commit()
            logger.info(f"[get_or_create_lead] Updated info for lead {lead.id}")
            
        logger.info(f"[get_or_create_lead] Existing lead identified: {lead.name} (ID: {lead.id})")
        return {
            "lead_id": lead.id,
            "name": lead.name,
            "phone": lead.phone,
            "email": lead.email,
            "message": "Existing lead identified and confirmed."
        }

@mcp.tool()
def smart_search(query: str):
    """
    Search for a lead or product across the CRM using a flexible query.
    """
    with SessionLocal() as session:
        # Search leads
        lead_res = session.execute(text("SELECT id, name, phone FROM lead WHERE name ILIKE :q OR phone ILIKE :q"), {"q": f"%{query}%"})
        leads = [dict(row._mapping) for row in lead_res]
        
        # Search products
        prod_res = session.execute(text("SELECT name, price FROM product WHERE name ILIKE :q"), {"q": f"%{query}%"})
        prods = [dict(row._mapping) for row in prod_res]
        
        return {"leads": leads, "products": prods}
    
@mcp.tool()
def check_icp_qualification(company_size: str, industry: str, employees: int = 0) -> dict:
    """
    Check if lead meets Rio's Ideal Customer Profile (ICP).
    ICP Criteria:
    - Company size: Enterprise (1000+), Mid-Market (100-999), SMB (10-99)
    - Industries: Tech, Healthcare, Finance, Retail, Manufacturing, SaaS
    - Min employees: 10
    
    Returns: {"is_qualified": bool, "reason": str, "priority": "high"|"medium"|"low"}
    """
    qualified_industries = ["Tech", "Healthcare", "Finance", "Retail", "Manufacturing", "SaaS"]
    
    reasons = []
    is_qualified = True
    priority = "low"
    
    # Check industry
    if industry.lower() in [ind.lower() for ind in qualified_industries]:
        reasons.append(f"✓ Industry '{industry}' is target market")
    else:
        reasons.append(f"✗ Industry '{industry}' not in target markets")
        is_qualified = False
    
    # Check company size
    size_map = {
        "enterprise": {"min": 1000, "priority": "high"},
        "mid-market": {"min": 100, "priority": "high"},
        "smb": {"min": 10, "priority": "medium"}
    }
    
    size_key = company_size.lower()
    if size_key in size_map:
        if employees >= size_map[size_key]["min"]:
            reasons.append(f"✓ Company size '{company_size}' matches profile")
            priority = size_map[size_key]["priority"]
        else:
            reasons.append(f"✗ Company size below minimum ({employees} < {size_map[size_key]['min']})")
            is_qualified = False
    else:
        reasons.append(f"? Unknown company size: {company_size}")
    
    return {
        "is_qualified": is_qualified,
        "reason": " | ".join(reasons),
        "priority": priority
    }

@mcp.tool()
def get_product_info(product_name: str) -> dict:
    """
    Get product information using semantic search.
    Treats missing products as "temporarily unavailable".
    
    Returns: {"name": str, "price": str, "stock": int, "note": str, "status": str}
    """
    # Perform multi-match semantic search in ChromaDB (top 3)
    semantic_results = search_products(product_name, n_results=3)
    
    if not semantic_results:
        return {
            "error": "Product not found",
            "status": "Unavailable",
            "message": "No matching products found in our catalog."
        }
    
    # Process results to find best available and alternatives
    with SessionLocal() as session:
        main_product = None
        alternatives = []
        
        for i, res in enumerate(semantic_results):
            p_name = res["name"]
            p_id = res.get("id")
            
            # Fetch from DB
            db_product = None
            if p_id:
                db_product = session.get(Product, p_id)
            if not db_product:
                statement = select(Product).where(Product.name == p_name)
                db_product = session.execute(statement).scalar_one_or_none()
            
            if not db_product:
                logger.warning(f"⚠️ Stale index entry found: {p_name} (ID: {p_id}) - Missing in Postgres")
                continue

            prod_details = {
                "name": db_product.name,
                "price": db_product.price,
                "stock": db_product.stock,
                "status": "Available" if db_product.stock > 0 else "Out of Stock",
                "note": db_product.note or "No additional notes"
            }

            if not main_product:
                main_product = prod_details
            else:
                alternatives.append(prod_details)

        if not main_product:
            return {
                "error": "Database mismatch",
                "status": "Unavailable",
                "message": "We found semantic matches but they are missing from the primary database. Please try a different search or re-sync catalog."
            }

        response = main_product.copy()
        if alternatives:
            response["alternative_suggestions"] = alternatives
            # Add a hint for the AI to mention alternatives if main is out of stock
            if main_product["stock"] <= 0:
                response["sales_hint"] = "The requested item is out of stock. PLEASE RECOMMEND one of the alternative suggestions below to the customer."
        
        return response

@mcp.tool()
def sync_product_catalog() -> dict:
    """Manual trigger to sync Postgres products with ChromaDB semantic index."""
    with SessionLocal() as session:
        products = session.execute(select(Product)).scalars().all()
        sync_products_to_chroma(products)
        return {"status": "success", "synced_count": len(products)}

@mcp.tool()
def check_guardrails(requested_discount_percent: float, requested_price: float = None) -> dict:
    """
    Check if discount is within Rio's approved guardrails.
    Guardrails:
    - Max discount: 10% without manager approval
    - If >10%: Requires manager (human) review
    
    Returns: {"approved": bool, "max_allowed_discount": float, "requires_manager": bool, "message": str}
    """
    MAX_AUTO_DISCOUNT = 10.0
    
    if requested_discount_percent <= MAX_AUTO_DISCOUNT:
        return {
            "approved": True,
            "max_allowed_discount": MAX_AUTO_DISCOUNT,
            "requires_manager": False,
            "message": f"✓ Discount of {requested_discount_percent}% is within auto-approved limits"
        }
    else:
        return {
            "approved": False,
            "max_allowed_discount": MAX_AUTO_DISCOUNT,
            "requires_manager": True,
            "message": f"✗ Discount of {requested_discount_percent}% exceeds limit. Requires manager approval. Auto-approved max: {MAX_AUTO_DISCOUNT}%"
        }

@mcp.tool()
def send_communication(lead_id: int, channels: list[str], content: str, subject: str = "Message from Rio AI", email: str = None, phone: str = None) -> dict:
    """
    Sends information to a lead via requested channels (email and/or whatsapp).
    Use this to share product specs, brochures, addresses, or any other requested info.
    
    Args:
    - lead_id: The ID of the lead.
    - channels: A list of channels to use, e.g., ["email"], ["whatsapp"], or ["email", "whatsapp"].
    - content: The detailed information to share.
    - subject: Subject line (used for Email).
    - email: Optional email address to update the lead and use for sending.
    - phone: Optional phone number to update the lead and use for WhatsApp.
    """
    logger.info(f"[send_communication] sending to lead {lead_id} via {channels}")
    
    with SessionLocal() as session:
        lead = session.query(Lead).filter(Lead.id == lead_id).first()
        if not lead:
            return {"success": False, "message": f"Lead {lead_id} not found."}

        # Update lead info if provided
        if email:
            lead.email = email
            logger.info(f"[send_communication] Updated lead {lead_id} email to {email}")
        if phone:
            lead.phone = phone
            logger.info(f"[send_communication] Updated lead {lead_id} phone to {phone}")
        
        if email or phone:
            session.commit()
            session.refresh(lead)

        results = {}
        successful_channels = []

        # 1. Handle Email
        if "email" in channels:
            target_email = email if email else lead.email
            if not target_email:
                results["email"] = "Failed: No email address on file or provided."
            elif not EMAIL_SERVICE_AVAILABLE:
                results["email"] = "Failed: Email service unavailable."
            else:
                html_content = get_styled_html(subject, content, lead.name)
                success = send_smtp_email(target_email, subject, content, html_body=html_content)
                if success:
                    results["email"] = "Sent"
                    successful_channels.append("Email")
                else:
                    results["email"] = "Failed (SMTP error)"

        # 2. Handle WhatsApp
        if "whatsapp" in channels:
            target_phone = phone if phone else lead.phone
            if not target_phone:
                results["whatsapp"] = "Failed: No phone number on file or provided."
            elif not WHATSAPP_SERVICE_AVAILABLE:
                results["whatsapp"] = "Failed: WhatsApp service unavailable."
            else:
                success = send_whatsapp_message(target_phone, content)
                if success:
                    results["whatsapp"] = "Sent"
                    successful_channels.append("WhatsApp")
                else:
                    results["whatsapp"] = "Failed (Twilio error)"

        # 3. Log Interaction if anything was sent
        if successful_channels:
            channel_str = " & ".join(successful_channels)
            interaction = Interaction(
                lead_id=lead_id,
                type="Multi-Channel Communication",
                content=f"Sent {channel_str}: {content[:100]}...",
                timestamp=datetime.now(timezone.utc)
            )
            session.add(interaction)
            session.commit()
            
            return {
                "success": True, 
                "message": f"Communication sent via {channel_str}.",
                "details": results
            }
        
        return {
            "success": False, 
            "message": "No messages were sent. Verification failed for selected channels.",
            "details": results
        }

@mcp.tool()
def send_email(phone: str, email: str, subject: str, body: str) -> dict:
    """
    (Legacy) Sends a standalone email. For dynamic multi-channel requests, use `send_communication` instead.
    """
    logger.info(f"[send_email] Sending to {email} for phone {phone}")
    normalized_phone = normalize_phone(phone)
    with SessionLocal() as session:
        # 1. Fetch lead
        statement = select(Lead).where(Lead.phone == normalized_phone)
        lead = session.execute(statement).scalar_one_or_none()
        
        # Priority: provided email > DB email
        target_email = email or (lead.email if lead else None)
        if not target_email:
            return {"success": False, "message": "No email address available. Please ask user for email."}

        # 2. Update lead email if new
        if lead and email and lead.email != email:
            lead.email = email
            lead.notes = (lead.notes or "") + f"\n[AI]: Captured email address: {email}"
            session.add(lead)
            session.commit()

        # 3. Send Email
        html_content = get_styled_html(subject, body, lead.name if lead else "Valued Customer")
        success = send_smtp_email(target_email, subject, body, html_body=html_content)

        if success:
            # 4. Log Interaction
            interaction = Interaction(
                lead_id=lead.id if lead else 0,
                type="Email",
                content=f"Sent Email: {subject}",
                timestamp=datetime.now(timezone.utc)
            )
            session.add(interaction)

            # 5. Track Outcome (Stage: Interest)
            outcome = Outcome(
                lead_id=lead.id if lead else 0,
                type="EMAIL_SENT",
                stage="Interest",
                potential_value=1200.0,
                probability=0.05 
            )
            session.add(outcome)
            session.commit()
            return {"success": True, "message": f"Email '{subject}' sent to {target_email} and logged."}
        else:
            return {"success": False, "message": "SMTP failure. Check environmental variables."}

@mcp.tool()
def get_google_auth_url() -> dict:
    """
    Returns the URL to authenticate Rio with Google Calendar.
    Use this if the user asks how to authorize or link their Google account.
    """
    from google_calendar_service import GoogleMeetGenerator
    try:
        generator = GoogleMeetGenerator()
        auth_url = generator.get_auth_url()
        return {
            "success": True,
            "auth_url": auth_url,
            "message": "Please visit this URL to authorize Google Calendar, then provide the code using 'submit_google_auth_code'."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
def submit_google_auth_code(code: str) -> dict:
    """
    Submits the Google authorization code to finalize linking.
    """
    from google_calendar_service import GoogleMeetGenerator
    try:
        generator = GoogleMeetGenerator()
        success = generator.finalize_auth(code)
        return {
            "success": success,
            "message": "Google Calendar linked successfully!" if success else "Failed to link Google Calendar. Check logs."
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@mcp.tool()
async def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo", lead_email: str = None, user: User = None) -> dict:
    """
    Book a meeting/demo for a qualified lead with Google Meet link.
    This MCP tool is self-contained - it handles all side effects internally:
    
    ACTIONS PERFORMED:
    1. Database: Fetch lead (or create if missing email)
    2. Google Calendar: Create event with Google Meet link
    3. Email: Send calendar invite with Meet link to lead
    4. Database: Create appointment record
    5. Logging: Track all operations
    
    Args:
    - lead_id (required): Database ID of the lead
    - proposed_time (required): Meeting time (natural language or ISO format)
    - meeting_type: "demo", "consultation", "follow-up", "discovery"
    - lead_email (optional): If provided and lead has no email, will update lead record
    
    Returns: {
        "confirmed": bool,
        "appointment_id": int,
        "lead_name": str,
        "lead_email": str,
        "google_meet_link": str,
        "calendar_url": str,
        "email_sent": bool,
        "needs_email": bool,
        "message": str,
        "auth_url": str (if Google Calendar needs authentication)
    }
    """
    logger.info(f"[book_meeting] Starting: lead_id={lead_id}, time={proposed_time}, type={meeting_type}")
    
    with SessionLocal() as session:
        try:
            # STEP 1: Fetch lead info from database
            lead_result = session.execute(
                text("SELECT id, name, email FROM lead WHERE id = :lid"),
                {"lid": lead_id}
            )
            lead = lead_result.first()
            
            if not lead:
                error_msg = f"Lead with ID {lead_id} not found"
                return {"confirmed": False, "error": error_msg, "needs_email": False}
            
            lead_dict = dict(lead._mapping)
            
            # STEP 1B: Handle missing email
            if not lead_dict.get("email"):
                return {
                    "confirmed": False,
                    "needs_email": True,
                    "lead_id": lead_id,
                    "lead_name": lead_dict["name"],
                    "message": f"⚠️ {lead_dict['name']} needs an email address for the invite."
                }

            # STEP 2: Authenticate & Create Google Meet link
            google_meet_link = None
            calendar_url = None
            auth_needed = False
            auth_url = None
            time_to_use = proposed_time # Initialize time_to_use

            if GOOGLE_CALENDAR_AVAILABLE:
                from google_calendar_service import GoogleMeetGenerator
                generator = GoogleMeetGenerator(user=user, session=session)
                auth_result = generator.validate_authentication()
                
                if auth_result["status"] != "valid":
                    auth_url = generator.get_auth_url()
                    auth_message = auth_result["message"]
                    logger.warning(f"[book_meeting] Auth issue: {auth_message}")
                    return {
                        "confirmed": False,
                        "message": f"⚠️ {auth_message} Please use 'get_google_auth_url' to reconnect.",
                        "auth_url": auth_url
                    }
                else:
                    # Normalize time before passing to Google Calendar
                    parsed_dt = await normalize_date_ai(proposed_time)
                    time_to_use = parsed_dt.isoformat() if parsed_dt else proposed_time
                    
                    meet_result = await generator.create_google_meet_event(
                        lead_name=lead_dict["name"],
                        lead_email=lead_dict["email"],
                        proposed_time=time_to_use,
                        meeting_type=meeting_type
                    )
                    
                    if meet_result.get("success"):
                        google_meet_link = meet_result.get("google_meet_link")
                        calendar_url = meet_result.get("calendar_link")
                        calendar_event_id = meet_result.get("calendar_event_id")
                        logger.info(f"[book_meeting] Google Meet created: {google_meet_link}, Event ID: {calendar_event_id}")
                    else:
                        logger.warning(f"[book_meeting] Meet creation failed: {meet_result.get('error')}")
            
            # STEP 3: Create appointment record in database
            appointment_insert = text("""
                INSERT INTO appointment (created_at, updated_at, created_by, updated_by, lead_id, appointment_time, status, meeting_link, calendar_event_id)
                VALUES (:created_at, :updated_at, :created_by, :updated_by, :lid, :atime, :status, :meet_link, :event_id)
                RETURNING id
            """)
            
            now = datetime.now(timezone.utc)
            result = session.execute(
                appointment_insert,
                {
                    "created_at": now,
                    "updated_at": now,
                    "created_by": "Rio AI",
                    "updated_by": "Rio AI",
                    "lid": lead_id,
                    "atime": time_to_use,
                    "status": "scheduled",
                    "meet_link": google_meet_link,
                    "event_id": calendar_event_id if 'calendar_event_id' in locals() else None
                }
            )
            session.commit()
            appointment_id = result.scalar()
            logger.info(f"[book_meeting] Appointment created: ID={appointment_id}")
            
            # STEP 4: Send email with calendar invite and Meet link
            email_sent = False
            email_error = None
            
            if EMAIL_SERVICE_AVAILABLE and lead_dict.get("email"):
                try:
                    email_subject = f"Your {meeting_type.title()} Meeting is Confirmed - Rio Sales Assistant"
                    
                    # Build email body with Google Meet link if available
                    meet_section = ""
                    if google_meet_link:
                        meet_section = f"""
                        <div style="background-color: #e8f5e9; padding: 20px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #27ae60;">
                            <h3 style="color: #27ae60; margin-top: 0;">📞 Join on Google Meet</h3>
                            <p style="margin: 10px 0;">
                                <a href="{google_meet_link}" 
                                   style="display: inline-block; background-color: #4285f4; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold; font-size: 16px;">
                                    Join Google Meet
                                </a>
                            </p>
                            <p style="color: #666; font-size: 12px; margin: 10px 0 0 0;">
                                📌 This is an automated Google Meet link. You can join directly from this email.
                            </p>
                        </div>
                        """
                    
                    email_body = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif;">
                    <div style="max-width: 600px; margin: 0 auto;">
                        <h2 style="color: #2c3e50; border-bottom: 3px solid #27ae60; padding-bottom: 10px;">
                            {meeting_type.title()} Confirmed!
                        </h2>
                        
                        <p>Hi <strong>{lead_dict['name']}</strong>,</p>
                        
                        <p>Great news! Your {meeting_type} has been scheduled successfully.</p>
                        
                        <div style="background-color: #f8f9fa; padding: 20px; border-radius: 5px; margin: 20px 0;">
                            <h3 style="color: #27ae60; margin-top: 0;">📅 Meeting Details:</h3>
                            <ul style="list-style: none; padding: 0;">
                                <li style="padding: 8px 0;"><strong>Type:</strong> {meeting_type.title()}</li>
                                <li style="padding: 8px 0;"><strong>Time:</strong> {proposed_time}</li>
                                <li style="padding: 8px 0;"><strong>Confirmation ID:</strong> #{appointment_id}</li>
                            </ul>
                        </div>
                        
                        {meet_section}
                        
                        <p>
                            <a href="#" 
                               style="display: inline-block; background-color: #27ae60; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                                View Meeting Details
                            </a>
                        </p>
                        
                        <p>If you need to reschedule or have any questions, please reply to this email or contact us directly.</p>
                        
                        <p>Looking forward to our conversation!</p>
                        
                        <div style="border-top: 1px solid #ecf0f1; padding-top: 20px; margin-top: 30px; color: #7f8c8d; font-size: 12px;">
                            <p>
                            <strong>Rio</strong> - Your Digital Sales Representative<br/>
                            Powered by Advanced Conversational AI<br/>
                            </p>
                        </div>
                    </div>
                    </body>
                    </html>
                    """
                    
                    send_smtp_email(
                        to_email=lead_dict["email"],
                        subject=email_subject,
                        body=email_body
                    )
                    email_sent = True
                    logger.info(f"[book_meeting] Email sent to {lead_dict['email']}")
                    
                    # Log Interaction for the Confirmation Email
                    interaction = Interaction(
                        lead_id=lead_id,
                        type="Email",
                        content=f"Sent Email: {email_subject}",
                        timestamp=datetime.now(timezone.utc)
                    )
                    session.add(interaction)
                    session.commit()
                    
                except Exception as e:
                    email_error = str(e)
                    logger.error(f"[book_meeting] Email failed: {email_error}", exc_info=True)
            else:
                if not EMAIL_SERVICE_AVAILABLE:
                    logger.warning("[book_meeting] Email service not available - skipping email")
                if not lead_dict.get("email"):
                    logger.warning(f"[book_meeting] No email address for lead {lead_id}")
            
            # STEP 5: Return success response
            crm_calendar_url = "#"
            
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                "lead_name": lead_dict["name"],
                "lead_email": lead_dict["email"],
                "google_meet_link": google_meet_link,
                "calendar_url": calendar_url or crm_calendar_url,
                "email_sent": email_sent,
                "meeting_type": meeting_type,
                "proposed_time": proposed_time,
                "needs_email": False,
                "message": f"✅ {meeting_type.title()} confirmed for {lead_dict['name']} on {proposed_time}" + 
                          (f" | Meet: {google_meet_link[:50]}..." if google_meet_link else "") +
                          (f" | Invite sent to {lead_dict['email']}" if email_sent else " (email not sent)")
            }
            
        except Exception as e:
            error_msg = f"Failed to book meeting: {str(e)}"
            logger.error(f"[book_meeting] {error_msg}", exc_info=True)
            return {
                "confirmed": False,
                "error": error_msg,
                "email_sent": False
            }

@mcp.tool()
async def book_demo(lead_id: int, name: str, phone: str, demo_date: str, products: str, city: str = None, state: str = None, pincode: str = None, demo_type: str = "Online", email: str = None, notes: str = None, user: User = None) -> dict:
    """
    Records a demo request with contact information, location, and product interest.
    Use this when a lead wants to schedule a demo for specific products.
    
    Args:
    - lead_id: The ID of the lead.
    - name: Caller's name.
    - phone: Caller's phone number.
    - city: Caller's city.
    - state: Caller's state.
    - pincode: Caller's pincode.
    - demo_date: The date and time requested for the demo (natural language).
    - products: The specific products or services the lead is interested in.
    - email: Caller's email address.
    - notes: Any additional requirements for the demo.
    """
    normalized_phone = normalize_phone(phone)
    logger.info(f"[book_demo] Recording demo for {name} ({phone}) at {city or 'Online'}, {state or ''} on {demo_date}. Type: {demo_type}")
    
    # Lead check - reuse get_or_create_lead logic or just verify lead_id
    with SessionLocal() as session:
        # Normalize phone
        normalized_phone = normalize_phone(phone)
        
        # Verify lead exists
        lead = session.get(Lead, lead_id)
        if not lead:
            # Fallback: search by phone
            lead = session.execute(select(Lead).where(Lead.phone == normalized_phone)).scalars().first()
            if not lead:
                # Create if absolutely missing
                lead = Lead(name=name, phone=normalized_phone, email=email, status="New", source="Demo Request")
                session.add(lead)
                session.commit()
                session.refresh(lead)
        
        # Parse date
        try:
            parsed_date = dateparser.parse(demo_date)
            if parsed_date.tzinfo is None:
                parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        except Exception:
            # AI normalizer fallback if simple parse fails
            from utils.date_normalizer import normalize_date_ai
            parsed_date = await normalize_date_ai(demo_date)
            if not parsed_date:
                parsed_date = datetime.now(timezone.utc)
            
        # Create Demo record
        demo = Demo(
            lead_id=lead.id,
            name=name, # Added name back as it's a required field for Demo model
            phone=normalized_phone, # Added phone back
            email=email, # Added email back
            city=city,
            state=state,
            pincode=pincode,
            products=products,
            demo_type=demo_type,
            notes=notes,
            status="Scheduled",
            demo_date=parsed_date
        )

        # Handle Online Demo with Google Meet link
        google_meet_link = None
        auth_error_msg = None
        if demo_type.lower() == "online" and GOOGLE_CALENDAR_AVAILABLE:
            from google_calendar_service import GoogleMeetGenerator
            generator = GoogleMeetGenerator(user=user, session=session)
            auth_result = generator.validate_authentication()
            
            if auth_result["status"] == "valid":
                # Extract clean meeting type from products
                meeting_title = f"{products} Demo"
                meet_result = await generator.create_google_meet_event(
                    lead_name=name,
                    lead_email=email or lead.email or "customer@example.com",
                    proposed_time=parsed_date.isoformat(),
                    meeting_type=meeting_title
                )
                if meet_result.get("success"):
                    google_meet_link = meet_result.get("google_meet_link")
                    demo.meeting_link = google_meet_link
                    demo.calendar_event_id = meet_result.get("calendar_event_id")
                    logger.info(f"[book_demo] Created Google Meet: {google_meet_link}, Event ID: {demo.calendar_event_id}")
                else:
                    auth_error_msg = f"Meet creation failed: {meet_result.get('error')}"
            else:
                auth_error_msg = f"Google Calendar connection expired: {auth_result['message']}"
                logger.warning(f"[book_demo] {auth_error_msg}")

        session.add(demo)
        session.commit()
        session.refresh(demo)
        
        # Log interaction
        interactionContent = f"Booked Demo for {products} | {name} ({normalized_phone}) at {city}, {state} ({pincode}) for {demo_date}"
        interaction = Interaction(
            lead_id=lead_id,
            type="Demo Booking",
            content=interactionContent,
            timestamp=datetime.now(timezone.utc)
        )
        session.add(interaction)
        session.commit()
        
        # Send Email Confirmation
        email_sent = False
        target_email = email
        if not target_email:
            # Try fetching from Lead table if not provided in tool call
            lead = session.get(Lead, lead_id)
            if lead and lead.email:
                target_email = lead.email
        
        if EMAIL_SERVICE_AVAILABLE and target_email:
            try:
                subject = f"{demo_type} Demo Confirmation - {products}"
                meet_text = f"\n\nGoogle Meet Link: {google_meet_link}" if google_meet_link else ""
                body = f"Hi {name},\n\nYour {demo_type.lower()} demo request for {products} has been recorded for {demo_date}.{meet_text}\n\nLocation: {city}, {state}, {pincode}\nOur team will contact you soon to finalize the details."
                html_content = get_styled_html(subject, body, name)
                email_sent = send_smtp_email(target_email, subject, body, html_body=html_content)
                if email_sent:
                    logger.info(f"[book_demo] Confirmation email sent to {target_email}")
            except Exception as e:
                logger.error(f"[book_demo] Email sending failed: {e}")

        return {
            "success": True,
            "demo_id": demo.id,
            "demo_date": parsed_date.isoformat(),
            "products": products,
            "google_meet_link": google_meet_link,
            "email_sent": email_sent,
            "message": f"✅ {demo_type} Demo for {products} recorded for {name} on {demo_date}." + 
                      (f" | Google Meet: {google_meet_link}" if google_meet_link else "") +
                      (f" | {auth_error_msg}" if auth_error_msg else "") +
                      (" | Confirmation email sent." if email_sent else "")
        }

@mcp.tool()
def get_call_latency_summary(interaction_id: int) -> str:
    """Retrieves a detailed latency breakdown for a specific call/interaction to identify bottlenecks."""
    try:
        with SessionLocal() as session:
            result = session.execute(
                text("SELECT stt_ms, llm_ms, tts_ms, stt_provider, llm_model, tts_provider FROM latencylog WHERE interaction_id = :lid"),
                {"lid": interaction_id}
            )
            logs = [dict(row._mapping) for row in result]
            if not logs:
                return f"No latency data found for interaction {interaction_id}."
            
            total_stt = sum(l["stt_ms"] for l in logs)
            total_llm = sum(l["llm_ms"] for l in logs)
            total_tts = sum(l["tts_ms"] for l in logs)
            count = len(logs)
            
            # Get unique providers/models for this call
            stt_provs = ", ".join(set(filter(None, [l.get("stt_provider") for l in logs])))
            llm_models = ", ".join(set(filter(None, [l.get("llm_model") for l in logs])))
            tts_provs = ", ".join(set(filter(None, [l.get("tts_provider") for l in logs])))
            
            summary = [
                f"📊 Detailed Latency Summary for Call {interaction_id} ({count} turns):",
                f"- **STT Provider(s)**: {stt_provs}",
                f"- **LLM Model(s)**: {llm_models}",
                f"- **TTS Provider(s)**: {tts_provs}",
                "",
                f"- Avg STT (Listening): {total_stt/count:.1f}ms",
                f"- Avg LLM (Thinking): {total_llm/count:.1f}ms",
                f"- Avg TTS (Speaking First-Byte): {total_tts/count:.1f}ms",
                f"- **Avg Turn Response Time**: {(total_stt+total_llm+total_tts)/count:.1f}ms",
                "\nRecommendations:",
                "1. If LLM is >1500ms, consider using a faster model (e.g., mistral-small)." if total_llm/count > 1500 else "LLM performance is good.",
                "2. If TTS is >800ms, use Cartesia as it has the lowest latency." if total_tts/count > 800 else "TTS performance is good."
            ]
            return "\n".join(summary)
    except Exception as e:
        return f"Error retrieving latency summary: {e}"

if __name__ == "__main__":
    mcp.run()
