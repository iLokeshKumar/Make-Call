import os
import logging
from datetime import datetime, timezone
from dateutil import parser as date_parser
from fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
from sqlmodel import select
from models.models import Lead, Interaction, Product, Appointment, LatencyLog, Outcome, Demo
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
    logger.warning("Email service not available - book_meeting will skip email sending")

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
    Looks up a lead by phone number or creates a new one if not found. 
    Use this towards the end of a conversation (e.g., when close to booking or finishing) 
    to identify the user. Avoid calling this at the very start of the call.
    """
    normalized_phone = normalize_phone(phone)
    logger.info(f"[get_or_create_lead] Searching for phone: {normalized_phone} (original: {phone})")
    
    with SessionLocal() as session:
        # Use ORM select for better compatibility with AuditMixin
        statement = select(Lead).where(Lead.phone == normalized_phone)
        lead = session.execute(statement).scalar_one_or_none()
        
        if not lead:
            logger.info(f"[get_or_create_lead] Creating new lead: {name}")
            lead = Lead(name=name, phone=normalized_phone, email=email, status="New")
            session.add(lead)
            session.commit()
            session.refresh(lead)
            return {"lead_id": lead.id, "name": lead.name, "status": "New", "message": "New lead created successfully."}
        
        # If lead exists but email is missing, update it
        if email and not lead.email:
            lead.email = email
            session.add(lead)
            session.commit()
            logger.info(f"[get_or_create_lead] Updated email for lead {lead.id}")
            
        logger.info(f"[get_or_create_lead] Existing lead found: {lead.name} (ID: {lead.id})")
        return {
            "lead_id": lead.id,
            "name": lead.name,
            "phone": lead.phone,
            "email": lead.email,
            "message": "Existing lead identified."
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
    logger.info(f"[get_product_info] Semantic search for: {product_name}")
    
    # Perform semantic search in ChromaDB
    semantic_results = search_products(product_name, n_results=1)
    
    if not semantic_results:
        return {
            "error": "Product not found in current catalog",
            "status": "Unavailable",
            "message": "This item is currently out of stock or not in our active catalog. Please continue the call."
        }
    
    best_match_name = semantic_results[0]["name"]
    logger.info(f"[get_product_info] Best semantic match: {best_match_name}")
    
    # Retrieve full details from Postgres for the best match
    with SessionLocal() as session:
        statement = select(Product).where(Product.name == best_match_name)
        product = session.execute(statement).scalar_one_or_none()
        
        if not product:
            return {
                "error": "Product metadata mismatch",
                "status": "Unavailable",
                "message": "We found a match but couldn't retrieve details. Treated as unavailable."
            }
        
        return {
            "name": product.name,
            "price": product.price,
            "stock": product.stock,
            "note": product.note or "No additional notes",
            "status": "Available" if product.stock > 0 else "Out of Stock",
            "in_stock": product.stock > 0
        }

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
def send_email(phone: str, email: str, subject: str, body: str) -> dict:
    """
    Sends an email to a lead and logs it in the interaction history.
    Args:
    - phone: The lead's phone number to link the interaction.
    - email: The email address (captured during call).
    - subject: Email subject.
    - body: Email content (markdown or plain text).
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
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo", lead_email: str = None) -> dict:
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
        "message": str
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
                logger.error(f"[book_meeting] {error_msg}")
                return {"confirmed": False, "error": error_msg, "needs_email": False}
            
            lead_dict = dict(lead._mapping)
            logger.info(f"[book_meeting] Lead found: {lead_dict['name']}")
            
            # STEP 1B: Handle missing email
            if not lead_dict.get("email"):
                if not lead_email:
                    # Email missing and not provided - need to ask Rio to collect it
                    logger.warning(f"[book_meeting] Lead {lead_id} has no email. Requesting from Rio...")
                    return {
                        "confirmed": False,
                        "needs_email": True,
                        "lead_id": lead_id,
                        "lead_name": lead_dict["name"],
                        "message": f"⚠️ {lead_dict['name']} doesn't have an email on file. Please ask them for their email address so we can send the meeting confirmation."
                    }
                else:
                    # Email provided by Rio - update the lead record
                    logger.info(f"[book_meeting] Updating email for lead {lead_id}: {lead_email}")
                    session.execute(
                        text("UPDATE lead SET email = :email WHERE id = :lid"),
                        {"email": lead_email, "lid": lead_id}
                    )
                    session.commit()
                    lead_dict["email"] = lead_email
                    logger.info(f"[book_meeting] Email updated successfully")
            
            # STEP 2: Create Google Meet link
            google_meet_link = None
            calendar_url = None
            
            if GOOGLE_CALENDAR_AVAILABLE and lead_dict.get("email"):
                try:
                    meet_result = create_google_meet_for_booking(
                        lead_name=lead_dict["name"],
                        lead_email=lead_dict["email"],
                        proposed_time=proposed_time,
                        meeting_type=meeting_type
                    )
                    
                    if meet_result.get("success"):
                        google_meet_link = meet_result.get("google_meet_link")
                        calendar_url = meet_result.get("calendar_link")
                        logger.info(f"[book_meeting] Google Meet link created: {google_meet_link}")
                    else:
                        logger.warning(f"[book_meeting] Google Meet creation failed: {meet_result.get('error')}")
                
                except Exception as e:
                    logger.warning(f"[book_meeting] Google Meet error: {e}")
            else:
                if not GOOGLE_CALENDAR_AVAILABLE:
                    logger.warning("[book_meeting] Google Calendar not available - Meet link will not be generated")
                elif not lead_dict.get("email"):
                    logger.warning("[book_meeting] Cannot create Meet link without email")
            
            # STEP 3: Create appointment record in database
            appointment_insert = text("""
                INSERT INTO appointment (lead_id, appointment_time, status, google_meet_link)
                VALUES (:lid, :atime, :status, :meet_link)
                RETURNING id
            """)
            
            result = session.execute(
                appointment_insert,
                {
                    "lid": lead_id,
                    "atime": proposed_time,
                    "status": "scheduled",
                    "meet_link": google_meet_link
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
                            <a href="https://rio-crm.example.com/appointment/{appointment_id}" 
                               style="display: inline-block; background-color: #27ae60; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                                View Full Meeting Details
                            </a>
                        </p>
                        
                        <p>If you need to reschedule or have any questions, please reply to this email or contact us directly.</p>
                        
                        <p>Looking forward to our conversation!</p>
                        
                        <div style="border-top: 1px solid #ecf0f1; padding-top: 20px; margin-top: 30px; color: #7f8c8d; font-size: 12px;">
                            <p>
                            <strong>Rio</strong> - Your AI Sales Assistant<br/>
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
            crm_calendar_url = f"https://rio-crm.example.com/appointment/{appointment_id}"
            
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
def book_demo(lead_id: int, name: str, phone: str, city: str, state: str, pincode: str, demo_date: str, email: str = None, notes: str = None) -> dict:
    """
    Records a demo request with contact and location details (city, state, pincode).
    Use this when a lead wants to schedule a demo and provides their location and contact info.
    
    Args:
    - lead_id: The ID of the lead.
    - name: Caller's name.
    - phone: Caller's phone number.
    - city: Caller's city.
    - state: Caller's state.
    - pincode: Caller's pincode.
    - demo_date: The date and time requested for the demo (natural language).
    - email: Caller's email address.
    - notes: Any additional requirements for the demo.
    """
    normalized_phone = normalize_phone(phone)
    logger.info(f"[book_demo] Recording demo for {name} ({normalized_phone}) at {city}, {state} on {demo_date}")
    
    # Parse demo date
    try:
        parsed_date = date_parser.parse(demo_date)
        if parsed_date.tzinfo is None:
            parsed_date = parsed_date.replace(tzinfo=timezone.utc)
    except Exception as e:
        logger.warning(f"[book_demo] Date parsing failed for '{demo_date}': {e}. Using current time as fallback.")
        parsed_date = datetime.now(timezone.utc)

    with SessionLocal() as session:
        demo = Demo(
            lead_id=lead_id,
            name=name,
            phone=normalized_phone,
            email=email,
            city=city,
            state=state,
            pincode=pincode,
            notes=notes,
            status="Scheduled",
            demo_date=parsed_date
        )
        session.add(demo)
        session.commit()
        session.refresh(demo)
        
        # Log interaction
        interaction = Interaction(
            lead_id=lead_id,
            type="Demo Booking",
            content=f"Booked Demo for {name} ({normalized_phone}) at {city}, {state} ({pincode}) for {demo_date}",
            timestamp=datetime.now(timezone.utc)
        )
        session.add(interaction)
        session.commit()
        
        # Send Email Confirmation if email is available
        email_sent = False
        target_email = email
        if not target_email:
            # Try fetching from Lead table if not provided in tool call
            lead = session.get(Lead, lead_id)
            if lead and lead.email:
                target_email = lead.email
        
        if EMAIL_SERVICE_AVAILABLE and target_email:
            try:
                subject = f"Demo Confirmation - {name}"
                body = f"Hi {name},\n\nYour demo request has been recorded for {demo_date}.\n\nLocation: {city}, {state}, {pincode}\nOur team will contact you soon."
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
            "email_sent": email_sent,
            "message": f"✅ Demo successfully recorded for {name} at {city}, {state} for {demo_date}." + (" Confirmation email sent." if email_sent else "")
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
