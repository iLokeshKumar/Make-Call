import os
import logging
from fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)

# Setup MCP Server
mcp = FastMCP("Rio CRM Navigator")

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Import email service for MCP tool use
try:
    from email_service import send_smtp_email
    EMAIL_SERVICE_AVAILABLE = True
except ImportError:
    EMAIL_SERVICE_AVAILABLE = False
    logger.warning("Email service not available - book_meeting will skip email sending")

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
    Get exact product information from inventory.
    This tool prevents AI hallucination about prices.
    
    Returns: {"name": str, "price": float, "stock": int, "min_authorized_price": float, "lead_time_days": int}
    """
    with SessionLocal() as session:
        result = session.execute(
            text("SELECT name, price, stock, note FROM product WHERE LOWER(name) ILIKE :pname LIMIT 1"),
            {"pname": f"%{product_name}%"}
        )
        product = result.first()
        
        if not product:
            return {"error": f"Product '{product_name}' not found in catalog"}
        
        product_dict = dict(product._mapping)
        
        # Parse note for metadata (e.g., "lead_time: 5 days")
        lead_time = 3  # default
        min_price = product_dict["price"] * 0.9  # default 10% minimum discount
        
        if product_dict.get("note"):
            # Example: "lead_time: 7 days | min_discount: 15%"
            if "lead_time:" in product_dict["note"]:
                import re
                match = re.search(r"lead_time:\s*(\d+)", product_dict["note"])
                if match:
                    lead_time = int(match.group(1))
        
        return {
            "name": product_dict["name"],
            "price": float(product_dict["price"]),
            "stock": product_dict["stock"],
            "min_authorized_price": float(min_price),
            "lead_time_days": lead_time,
            "in_stock": product_dict["stock"] > 0
        }

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
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo") -> dict:
    """
    Book a meeting/demo for a qualified lead AND send confirmation email.
    This MCP tool is self-contained - it handles all side effects internally:
    
    ACTIONS PERFORMED:
    1. Database: Create appointment record
    2. Email: Send calendar invite to lead email
    3. Logging: Track all operations
    
    Args:
    - lead_id (required): Database ID of the lead
    - proposed_time (required): Meeting time (natural language or ISO format)
    - meeting_type: "demo", "consultation", "follow-up", "discovery"
    
    Returns: {
        "confirmed": bool,
        "appointment_id": int,
        "lead_name": str,
        "lead_email": str,
        "calendar_url": str,
        "email_sent": bool,
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
                return {"confirmed": False, "error": error_msg}
            
            lead_dict = dict(lead._mapping)
            logger.info(f"[book_meeting] Lead found: {lead_dict['name']} ({lead_dict['email']})")
            
            # STEP 2: Create appointment record in database
            appointment_insert = text("""
                INSERT INTO appointment (lead_id, appointment_time, status)
                VALUES (:lid, :atime, :status)
                RETURNING id
            """)
            
            result = session.execute(
                appointment_insert,
                {
                    "lid": lead_id,
                    "atime": proposed_time,
                    "status": "scheduled"
                }
            )
            session.commit()
            appointment_id = result.scalar()
            logger.info(f"[book_meeting] Appointment created: ID={appointment_id}")
            
            # STEP 3: Send email with calendar invite
            email_sent = False
            email_error = None
            
            if EMAIL_SERVICE_AVAILABLE and lead_dict.get("email"):
                try:
                    email_subject = f"Your {meeting_type.title()} Meeting is Confirmed - Rio Sales Assistant"
                    
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
                            <h3 style="color: #27ae60; margin-top: 0;">Meeting Details:</h3>
                            <ul style="list-style: none; padding: 0;">
                                <li style="padding: 8px 0;"><strong>Type:</strong> {meeting_type.title()}</li>
                                <li style="padding: 8px 0;"><strong>Time:</strong> {proposed_time}</li>
                                <li style="padding: 8px 0;"><strong>Confirmation ID:</strong> #{appointment_id}</li>
                            </ul>
                        </div>
                        
                        <p>
                            <a href=\"https://rio-crm.example.com/appointment/{appointment_id}\" 
                               style=\"display: inline-block; background-color: #27ae60; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;\">
                                View Meeting Details
                            </a>
                        </p>
                        
                        <p>If you need to reschedule or have any questions, please reply to this email or contact us directly.</p>
                        
                        <p>Looking forward to our conversation!</p>
                        
                        <div style=\"border-top: 1px solid #ecf0f1; padding-top: 20px; margin-top: 30px; color: #7f8c8d; font-size: 12px;\">
                            <p>\n                            <strong>Rio</strong> - Your AI Sales Assistant<br/>\n                            Powered by Advanced Conversational AI<br/>\n                            </p>\n                        </div>\n                    </div>\n                    </body>\n                    </html>\n                    """
                    
                    send_smtp_email(
                        to_email=lead_dict["email"],
                        subject=email_subject,
                        body=email_body
                    )
                    email_sent = True
                    logger.info(f"[book_meeting] Email sent to {lead_dict['email']}")
                    
                except Exception as e:
                    email_error = str(e)
                    logger.error(f"[book_meeting] Email failed: {email_error}", exc_info=True)
            else:
                if not EMAIL_SERVICE_AVAILABLE:
                    logger.warning("[book_meeting] Email service not available - skipping email")
                if not lead_dict.get("email"):
                    logger.warning(f"[book_meeting] No email address for lead {lead_id}")
            
            # STEP 4: Return success response
            calendar_url = f"https://rio-crm.example.com/appointment/{appointment_id}"
            
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                "lead_name": lead_dict["name"],
                "lead_email": lead_dict["email"],
                "calendar_url": calendar_url,
                "email_sent": email_sent,
                "meeting_type": meeting_type,
                "proposed_time": proposed_time,
                "message": f"✅ {meeting_type.title()} confirmed for {lead_dict['name']} on {proposed_time}" + 
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

if __name__ == "__main__":
    mcp.run()
