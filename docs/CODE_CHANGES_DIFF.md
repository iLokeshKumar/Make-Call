# Code Changes - Before/After Comparison

## File 1: mcp_server.py

### Change 1: Added Logging and Email Service (Lines 1-27)

**BEFORE:**
```python
import os
from fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Setup MCP Server
mcp = FastMCP("Rio CRM Navigator")

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

**AFTER:**
```python
import os
import logging  # ← NEW
from fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

load_dotenv()

# Setup logging  # ← NEW
logger = logging.getLogger(__name__)  # ← NEW

# Setup MCP Server
mcp = FastMCP("Rio CRM Navigator")

# Database Setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Import email service for MCP tool use  # ← NEW
try:  # ← NEW
    from email_service import send_smtp_email  # ← NEW
    EMAIL_SERVICE_AVAILABLE = True  # ← NEW
except ImportError:  # ← NEW
    EMAIL_SERVICE_AVAILABLE = False  # ← NEW
    logger.warning("Email service not available - book_meeting will skip email sending")  # ← NEW
```

### Change 2: Refactored book_meeting() Tool (Lines 192-344)

**BEFORE:**
```python
@mcp.tool()
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo") -> dict:
    """
    Book a meeting/demo for a qualified lead.
    This is a deterministic action (not agentic).
    
    Args:
    - lead_id: ID of the lead from database
    - proposed_time: ISO format datetime (e.g., "2026-01-25T14:00:00")
    - meeting_type: "demo", "consultation", "follow-up"
    
    Returns: {"confirmed": bool, "appointment_id": int, "calendar_url": str, "lead_name": str}
    """
    with SessionLocal() as session:
        # Fetch lead info
        lead_result = session.execute(text("SELECT id, name, email FROM lead WHERE id = :lid"), {"lid": lead_id})
        lead = lead_result.first()
        
        if not lead:
            return {"confirmed": False, "error": f"Lead with ID {lead_id} not found"}
        
        lead_dict = dict(lead._mapping)
        
        # Create appointment record
        try:
            appointment_insert = text("""
                INSERT INTO appointment (lead_id, appointment_time, status, type)
                VALUES (:lid, :atime, :status, :atype)
                RETURNING id
            """)
            
            result = session.execute(
                appointment_insert,
                {
                    "lid": lead_id,
                    "atime": proposed_time,
                    "status": "scheduled",
                    "atype": meeting_type
                }
            )
            session.commit()
            appointment_id = result.scalar()
            
            # Create calendar URL (mock Calendly format)
            calendar_url = f"https://rio-crm.example.com/appointment/{appointment_id}"
            
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                "calendar_url": calendar_url,
                "lead_name": lead_dict["name"],
                "lead_email": lead_dict["email"],
                "message": f"✓ Demo scheduled for {lead_dict['name']} on {proposed_time}"
            }
        except Exception as e:
            return {
                "confirmed": False,
                "error": f"Failed to book meeting: {str(e)}"
            }
```

**AFTER:**
```python
@mcp.tool()
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo") -> dict:
    """
    Book a meeting/demo for a qualified lead AND send confirmation email.  # ← UPDATED DOCSTRING
    This MCP tool is self-contained - it handles all side effects internally:  # ← NEW
    
    ACTIONS PERFORMED:  # ← NEW
    1. Database: Create appointment record  # ← NEW
    2. Email: Send calendar invite to lead email  # ← NEW
    3. Logging: Track all operations  # ← NEW
    
    Args:
    - lead_id (required): Database ID of the lead  # ← UPDATED
    - proposed_time (required): Meeting time (natural language or ISO format)  # ← UPDATED
    - meeting_type: "demo", "consultation", "follow-up", "discovery"  # ← UPDATED
    
    Returns: {  # ← UPDATED
        "confirmed": bool,
        "appointment_id": int,
        "lead_name": str,
        "lead_email": str,
        "calendar_url": str,
        "email_sent": bool,  # ← NEW
        "message": str
    }
    """
    logger.info(f"[book_meeting] Starting: lead_id={lead_id}, time={proposed_time}, type={meeting_type}")  # ← NEW
    
    with SessionLocal() as session:
        try:
            # STEP 1: Fetch lead info from database  # ← NEW COMMENT
            lead_result = session.execute(
                text("SELECT id, name, email FROM lead WHERE id = :lid"),
                {"lid": lead_id}
            )
            lead = lead_result.first()
            
            if not lead:
                error_msg = f"Lead with ID {lead_id} not found"  # ← UPDATED
                logger.error(f"[book_meeting] {error_msg}")  # ← NEW
                return {"confirmed": False, "error": error_msg}
            
            lead_dict = dict(lead._mapping)
            logger.info(f"[book_meeting] Lead found: {lead_dict['name']} ({lead_dict['email']})")  # ← NEW
            
            # STEP 2: Create appointment record in database  # ← NEW COMMENT
            appointment_insert = text("""
                INSERT INTO appointment (lead_id, appointment_time, status)  # ← REMOVED type column
                VALUES (:lid, :atime, :status)
                RETURNING id
            """)
            
            result = session.execute(
                appointment_insert,
                {
                    "lid": lead_id,
                    "atime": proposed_time,
                    "status": "scheduled"
                    # ← REMOVED "atype": meeting_type
                }
            )
            session.commit()
            appointment_id = result.scalar()
            logger.info(f"[book_meeting] Appointment created: ID={appointment_id}")  # ← NEW
            
            # STEP 3: Send email with calendar invite  # ← NEW SECTION
            email_sent = False  # ← NEW
            email_error = None  # ← NEW
            
            if EMAIL_SERVICE_AVAILABLE and lead_dict.get("email"):  # ← NEW
                try:  # ← NEW
                    email_subject = f"Your {meeting_type.title()} Meeting is Confirmed - Rio Sales Assistant"  # ← NEW
                    
                    email_body = f"""  # ← NEW - Detailed HTML email template
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
                            <a href="https://rio-crm.example.com/appointment/{appointment_id}" 
                               style="display: inline-block; background-color: #27ae60; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; font-weight: bold;">
                                View Meeting Details
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
                    
                    send_smtp_email(  # ← NEW - Actually send the email!
                        to_email=lead_dict["email"],
                        subject=email_subject,
                        body=email_body
                    )
                    email_sent = True  # ← NEW
                    logger.info(f"[book_meeting] Email sent to {lead_dict['email']}")  # ← NEW
                    
                except Exception as e:  # ← NEW
                    email_error = str(e)  # ← NEW
                    logger.error(f"[book_meeting] Email failed: {email_error}", exc_info=True)  # ← NEW
            else:  # ← NEW
                if not EMAIL_SERVICE_AVAILABLE:  # ← NEW
                    logger.warning("[book_meeting] Email service not available - skipping email")  # ← NEW
                if not lead_dict.get("email"):  # ← NEW
                    logger.warning(f"[book_meeting] No email address for lead {lead_id}")  # ← NEW
            
            # STEP 4: Return success response  # ← NEW COMMENT
            calendar_url = f"https://rio-crm.example.com/appointment/{appointment_id}"
            
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                "lead_name": lead_dict["name"],
                "lead_email": lead_dict["email"],
                "calendar_url": calendar_url,
                "email_sent": email_sent,  # ← NEW
                "meeting_type": meeting_type,  # ← NEW
                "proposed_time": proposed_time,  # ← NEW
                "message": f"✅ {meeting_type.title()} confirmed for {lead_dict['name']} on {proposed_time}" +  # ← UPDATED
                          (f" | Calendar invite sent to {lead_dict['email']}" if email_sent else " (email not sent)")  # ← NEW
            }
            
        except Exception as e:  # ← UPDATED
            error_msg = f"Failed to book meeting: {str(e)}"  # ← NEW
            logger.error(f"[book_meeting] {error_msg}", exc_info=True)  # ← NEW
            return {
                "confirmed": False,
                "error": error_msg,  # ← CHANGED from str(e)
                "email_sent": False  # ← NEW
            }
```

---

## File 2: tool_adapter.py

**COMPLETELY REWRITTEN** - Removed duplicate code, pure router pattern

### Changes Summary:

**REMOVED:**
- `from database import SessionLocal`
- `from sqlalchemy import text`
- All database/appointment creation code (50+ lines)
- Duplicate book_meeting implementation

**ADDED:**
- Comprehensive docstring explaining MCP architecture
- Email service note in book_meeting schema description
- Logging in execute_mcp_tool for debugging
- Clear "DESIGN PRINCIPLE" comments

**KEPT:**
- get_mistral_tools() function (schema only)
- execute_mcp_tool() routing logic
- Tool descriptions for documentation

### Key Differences:

**BEFORE book_meeting routing:**
```python
elif tool_name == "book_meeting":
    lead_id = arguments.get("lead_id")
    proposed_time = arguments.get("proposed_time")
    meeting_type = arguments.get("meeting_type", "demo")

    with SessionLocal() as session:
        try:
            # Fetch lead
            lead_result = session.execute(
                text("SELECT id, name, email FROM lead WHERE id = :lid"),
                {"lid": lead_id}
            )
            # ... 50 lines of duplicate code ...
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                # ... no email_sent field ...
            }
        except Exception as e:
            logger.error(f"Failed to book meeting: {e}")
            return {
                "confirmed": False,
                "error": f"Failed to book meeting: {str(e)}"
            }
```

**AFTER book_meeting routing:**
```python
elif tool_name == "book_meeting":
    # Delegate to MCP tool (which handles DB + email internally)
    result = book_meeting(
        lead_id=arguments.get("lead_id"),
        proposed_time=arguments.get("proposed_time"),
        meeting_type=arguments.get("meeting_type", "demo")
    )
    logger.info(f"[execute_mcp_tool] {tool_name} returned: {result}")
    return result
```

---

## Summary of Changes

| Aspect | Before | After |
|--------|--------|-------|
| **book_meeting implementations** | 2 (tool_adapter + mcp_server) | 1 (mcp_server only) |
| **Email sending** | Never called | Integrated in tool |
| **Lines in tool_adapter.py** | 240+ with duplicate code | 241 pure routing |
| **Logging** | Minimal | Comprehensive per step |
| **Error handling** | Generic | Detailed with context |
| **Response object** | Incomplete | Complete with email_sent flag |
| **Code duplication** | 50+ lines | 0 lines |
| **Architecture pattern** | Workaround | Proper MCP |

---

## Impact

When refactored code runs:

1. **Database:** Appointment record created ✅
2. **Email:** Confirmation sent to lead ✅
3. **Response:** Rich object with status ✅
4. **Logging:** Full audit trail ✅
5. **Errors:** Graceful handling ✅

This is now **proper MCP architecture** with self-contained tools! 🎉
