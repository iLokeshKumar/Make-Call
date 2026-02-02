# MCP & Agents Setup Guide

## Overview

This document explains how to set up MCP (Model Context Protocol) and agents in the Rio CRM Navigator system for your outbound calling voice assistant.

---

## Part 1: Understanding MCP Architecture

### What is MCP?

**Model Context Protocol (MCP)** is a standardized way for AI assistants and language models to access tools and resources. Think of it as a bridge between:
- **AI/LLM Layer** (Claude, Mistral, etc.) - decides what to do
- **Business Logic Layer** (your database, APIs, services) - executes actions

### MCP vs Traditional Approach

| Traditional | MCP |
|---|---|
| Hard-coded tool calls in LLM prompts | Tools auto-discovered from MCP server |
| Manual parameter validation | Automatic schema validation |
| Tools coupled to main application | Decoupled server-client architecture |
| Difficult to extend with new tools | Easy: add @mcp.tool decorator |

---

## Part 2: Rio's MCP Server Architecture

### Current Setup: FastMCP Framework

```
FastMCP Server (mcp_server.py)
├── Resources (static data)
│   ├── crm://leads/summary
│   ├── crm://inventory
│   └── ... 
├── Tools (actionable operations)
│   ├── @mcp.tool get_lead(lead_id)
│   ├── @mcp.tool update_lead(lead_id, field, value)
│   ├── @mcp.tool get_call_history(lead_id)
│   ├── @mcp.tool search_leads(query)
│   ├── @mcp.tool book_meeting(lead_id, proposed_time, ...)
│   └── ...
└── Server Startup
    └── mcp.run() on execution
```

### Components

**1. FastMCP Instance**
```python
from fastmcp import FastMCP
mcp = FastMCP("Rio CRM Navigator")  # Creates the MCP server
```

**2. Resources** - Read-only contextual data
```python
@mcp.resource("crm://leads/summary")
def get_leads_summary():
    """Returns a summary of all leads in the system."""
    # Query database
    # Return structured data
```

**3. Tools** - Actionable operations AI can call
```python
@mcp.tool()
def book_meeting(lead_id, proposed_time, meeting_type="demo", lead_email=None):
    """Books a demo meeting with a lead and sends confirmation email."""
    # Perform side effects (DB update, API call, email)
    # Return result
```

---

## Part 3: MCP Server Setup

### Step 1: Basic MCP Server Initialization

**File: `mcp_server.py`**

```python
from fastmcp import FastMCP
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import os

load_dotenv()

# Initialize MCP Server
mcp = FastMCP("Rio CRM Navigator")

# Setup Database Connection
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:1234@localhost/calls")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

### Step 2: Add Resources (Read-Only Context)

Resources provide context that agents can reference without making changes.

```python
@mcp.resource("crm://leads/summary")
def get_leads_summary():
    """Returns a summary of all leads."""
    with SessionLocal() as session:
        result = session.execute(text(
            "SELECT id, name, phone, status, enrichment_status FROM lead"
        ))
        return [dict(row._mapping) for row in result]

@mcp.resource("crm://inventory")
def get_inventory():
    """Returns product inventory and stock levels."""
    with SessionLocal() as session:
        result = session.execute(text(
            "SELECT name, stock, price, note FROM product"
        ))
        return [dict(row._mapping) for row in result]
```

### Step 3: Add Tools (Actionable Operations)

Tools allow agents to perform actions. Each tool should handle side effects (DB updates, API calls, emails).

```python
@mcp.tool()
def get_lead(lead_id: int):
    """Fetches a specific lead's information."""
    with SessionLocal() as session:
        result = session.execute(
            text("SELECT * FROM lead WHERE id = :id"),
            {"id": lead_id}
        )
        lead = result.fetchone()
        if lead:
            return dict(lead._mapping)
        return {"error": f"Lead {lead_id} not found"}

@mcp.tool()
def update_lead(lead_id: int, field: str, value: str):
    """Updates a lead's field."""
    try:
        with SessionLocal() as session:
            session.execute(
                text(f"UPDATE lead SET {field} = :value WHERE id = :id"),
                {"value": value, "id": lead_id}
            )
            session.commit()
            return {"success": True, "message": f"Updated {field}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
```

### Step 4: Complex Tool with Side Effects (Example: book_meeting)

```python
@mcp.tool()
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo", lead_email: str = None):
    """
    Books a demo meeting with email collection and Google Meet link generation.
    
    Args:
        lead_id: ID of the lead
        proposed_time: Meeting time (e.g., "Tuesday 2 PM", "tomorrow 10 AM")
        meeting_type: Type of meeting (demo, followup, closing)
        lead_email: Optional - email to update if lead has no email
    
    Returns:
        Dictionary with confirmation details, Meet link, and email status
    """
    try:
        # STEP 1: Fetch lead from database
        with SessionLocal() as session:
            lead_result = session.execute(
                text("SELECT * FROM lead WHERE id = :id"),
                {"id": lead_id}
            )
            lead_dict = dict(lead_result.fetchone()._mapping)
        
        # STEP 1B: Email collection - if no email on file
        if not lead_dict.get("email"):
            if not lead_email:
                # First call: ask Rio to collect email
                return {
                    "confirmed": False,
                    "needs_email": True,
                    "message": "Please ask for their email address"
                }
            else:
                # Second call: update email and continue
                with SessionLocal() as session:
                    session.execute(
                        text("UPDATE lead SET email = :email WHERE id = :id"),
                        {"email": lead_email, "id": lead_id}
                    )
                    session.commit()
                lead_dict["email"] = lead_email
        
        # STEP 2: Generate Google Meet link
        google_meet_link = None
        if GOOGLE_CALENDAR_AVAILABLE:
            try:
                from google_calendar_service import create_google_meet_for_booking
                result = create_google_meet_for_booking(proposed_time)
                google_meet_link = result.get("google_meet_link")
            except Exception as e:
                logger.warning(f"Could not generate Meet link: {str(e)}")
        
        # STEP 3: Insert appointment into database
        with SessionLocal() as session:
            session.execute(text("""
                INSERT INTO appointment (lead_id, proposed_time, meeting_type, google_meet_link)
                VALUES (:lead_id, :time, :type, :meet_link)
            """), {
                "lead_id": lead_id,
                "time": proposed_time,
                "type": meeting_type,
                "meet_link": google_meet_link
            })
            session.commit()
        
        # STEP 4: Send confirmation email with Meet link
        email_sent = False
        if EMAIL_SERVICE_AVAILABLE and lead_dict.get("email"):
            try:
                from email_service import send_smtp_email
                email_body = f"""
                <h2>Demo Meeting Confirmed ✅</h2>
                <p>Hi {lead_dict['name']},</p>
                <p>Your demo meeting is scheduled for <strong>{proposed_time}</strong></p>
                """
                if google_meet_link:
                    email_body += f"""
                    <div style="background: #e8f5e9; padding: 20px; border-radius: 8px; margin: 20px 0;">
                        <p>Join the meeting:</p>
                        <a href="{google_meet_link}" style="background: #4285f4; color: white; 
                           padding: 12px 24px; text-decoration: none; border-radius: 4px;">
                            Join Google Meet
                        </a>
                    </div>
                    """
                
                send_smtp_email(lead_dict["email"], "Demo Meeting Confirmed", email_body)
                email_sent = True
            except Exception as e:
                logger.warning(f"Could not send email: {str(e)}")
        
        # STEP 5: Return success response
        return {
            "confirmed": True,
            "google_meet_link": google_meet_link,
            "email_sent": email_sent,
            "needs_email": False,
            "message": f"✅ {meeting_type.title()} confirmed for {lead_dict['name']} on {proposed_time}"
        }
        
    except Exception as e:
        logger.error(f"Book meeting error: {str(e)}", exc_info=True)
        return {"confirmed": False, "error": str(e)}
```

### Step 5: Start the MCP Server

```python
if __name__ == "__main__":
    mcp.run()
```

**Running the server:**
```bash
python mcp_server.py
```

Output:
```
MCP Server started on stdio
Tools available:
  - get_lead
  - update_lead
  - get_call_history
  - search_leads
  - book_meeting
  - ... (and more)

Resources available:
  - crm://leads/summary
  - crm://inventory
```

---

## Part 4: Agent Integration

### What is an Agent?

An **agent** is an AI system that:
1. **Observes** the current situation (lead data, call transcript)
2. **Thinks** about what to do next (analyze context, decide action)
3. **Acts** by calling MCP tools to make changes
4. **Repeats** based on tool results

### Rio's Agent Architecture

```
┌─────────────────────────────────────┐
│     Outbound Call Initiated         │
│     (Lead Phone Number)             │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│   Transcribe Speech with Deepgram   │
│   Get user's spoken words as text   │
└──────────────┬──────────────────────┘
               │
               ▼
┌─────────────────────────────────────┐
│    Rio Agent (Mistral LLM)          │
│  - Access to MCP tools              │
│  - CRM context (resources)          │
│  - Call history                     │
│  - Product knowledge                │
└──────────────┬──────────────────────┘
               │
               ▼
         ┌─────┴─────────┐
         │               │
         ▼               ▼
    Respond        Call Tool
    (Natural        (get_lead,
     Speech)        update_lead,
                    book_meeting,
                    etc.)
               │
               ▼
    ┌──────────────────────┐
    │ Execute Side Effects │
    │ • Update database    │
    │ • Send emails        │
    │ • Create events      │
    └──────────────────────┘
```

### Agent Implementation in main.py

The agent is the **Mistral LLM** with system prompts and access to MCP tools.

```python
from mistralai import Mistral as MistralClient

# Initialize agent
client = MistralClient(api_key=os.getenv("MISTRAL_API_KEY"))

async def mistral_voice_pipeline(lead_data: dict, conversation_history: list):
    """
    Rio's conversation brain - uses Mistral LLM with MCP tool access.
    """
    
    # Build system prompt with context and tool availability
    system_prompt = f"""
    You are Rio, a professional sales assistant.
    
    CONTEXT:
    - Lead: {lead_data['name']}
    - Phone: {lead_data['phone']}
    - Status: {lead_data['status']}
    - Call History: {lead_data.get('notes', 'None yet')}
    
    AVAILABLE ACTIONS:
    You can call these tools during the conversation:
    - get_lead(lead_id): Fetch lead information
    - update_lead(lead_id, field, value): Update lead data
    - book_meeting(lead_id, proposed_time, meeting_type, lead_email): Schedule demo
    - search_leads(query): Find similar leads
    - get_call_history(lead_id): View past interactions
    
    CONVERSATION FLOW:
    1. Greet professionally
    2. Understand their needs
    3. Demonstrate product value
    4. Overcome objections
    5. Close or schedule follow-up using book_meeting()
    
    When booking, use tool calls naturally in conversation.
    If lead has no email, ask for it and call book_meeting with lead_email parameter.
    """
    
    # Make API call with conversation history
    response = client.messages.create(
        model="mistral-large-latest",
        messages=[
            {"role": "system", "content": system_prompt},
            *conversation_history  # Past turns
        ],
        max_tokens=500,
        tools=[
            # MCP tools would be injected here in production
            # or called via tool_choice parameter
        ]
    )
    
    return response.content[0].text
```

### Agent State Management

Agents maintain conversation state across multiple turns:

```python
# In-call agent state
call_session = {
    "lead_id": 123,
    "lead_data": {...},
    "conversation_history": [
        {"role": "system", "content": "You are Rio..."},
        {"role": "assistant", "content": "Hello! This is Rio from..."},
        {"role": "user", "content": "Hi, what's this about?"},
        {"role": "assistant", "content": "Great question. We help companies..."},
        {"role": "user", "content": "Sounds interesting, I'm busy now though"},
        {"role": "assistant", "content": "No problem! Can I schedule a quick demo?"},
    ],
    "tool_results": [
        {"tool": "book_meeting", "result": "Meeting scheduled for Tuesday 2 PM"}
    ],
    "call_recording": "..." 
}
```

---

## Part 5: MCP Tools Best Practices

### 1. Always Include Error Handling

```python
@mcp.tool()
def risky_operation(lead_id: int):
    """A tool that might fail."""
    try:
        # Perform operation
        pass
    except ValueError as e:
        return {"success": False, "error": f"Invalid input: {str(e)}"}
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return {"success": False, "error": "Operation failed unexpectedly"}
```

### 2. Use Type Hints for Auto-Generated Documentation

```python
@mcp.tool()
def find_leads(
    company_name: str,
    industry: str = None,
    min_employees: int = 10
) -> dict:
    """
    Find leads matching criteria.
    
    Args:
        company_name: Name of the company to search for
        industry: Optional industry filter (tech, finance, etc.)
        min_employees: Minimum company size (default: 10)
    
    Returns:
        Dictionary with matching leads list
    """
    pass
```

### 3. Make Tools Idempotent When Possible

```python
@mcp.tool()
def create_contact(name: str, email: str):
    """Create a contact (idempotent - safe to call multiple times)."""
    with SessionLocal() as session:
        # Check if already exists
        existing = session.execute(
            text("SELECT id FROM contact WHERE email = :email"),
            {"email": email}
        ).fetchone()
        
        if existing:
            return {"success": True, "contact_id": existing[0], "created": False}
        
        # Create new contact
        session.execute(
            text("INSERT INTO contact (name, email) VALUES (:name, :email)"),
            {"name": name, "email": email}
        )
        session.commit()
        return {"success": True, "created": True}
```

### 4. Keep Tool Responses Clear and Structured

```python
# ❌ BAD - Vague response
return {"status": "ok", "data": {...}}

# ✅ GOOD - Clear structure
return {
    "success": True,
    "action_taken": "email_sent",
    "details": {
        "recipient": "john@example.com",
        "subject": "Demo Meeting Confirmed",
        "sent_at": "2026-01-29 14:30:00"
    },
    "next_step": "Awaiting lead's response"
}
```

---

## Part 6: Testing MCP Tools

### Test 1: Start the Server

```bash
python mcp_server.py
```

Expected output:
```
MCP Server started
Tools available: [list of tools]
```

### Test 2: Call a Tool Directly (for debugging)

```python
# In a test script
import mcp_server

# Get the tool
get_lead_tool = mcp_server.mcp.get_tool("get_lead")

# Call it directly
result = get_lead_tool(lead_id=1)
print(result)
```

### Test 3: Integration Test with Agent

```python
# Simulate an agent calling a tool
async def test_booking_workflow():
    # Agent decides to book a meeting
    result = book_meeting(
        lead_id=1,
        proposed_time="Friday 2 PM",
        meeting_type="demo",
        lead_email="john@example.com"
    )
    
    assert result["confirmed"] == True
    assert result["google_meet_link"] is not None
    assert result["email_sent"] == True
```

---

## Part 7: Common Setup Issues

### Issue 1: Tools Not Available to Agent

**Symptom:** Agent tries to call tool but gets "tool not found"

**Solution:** Make sure MCP server is running before agent attempts calls
```bash
# Terminal 1: Start MCP server
python mcp_server.py

# Terminal 2: Start agent/main application
python main.py
```

### Issue 2: Database Connection Failing

**Symptom:** "Failed to connect to PostgreSQL"

**Solution:** Check DATABASE_URL in .env
```python
# .env
DATABASE_URL=postgresql://username:password@localhost/calls

# Verify connection
python -c "from sqlalchemy import create_engine; engine = create_engine('postgresql://username:password@localhost/calls'); print(engine.connect())"
```

### Issue 3: Tool Returns Errors to Agent

**Symptom:** Agent receives error responses but can't recover

**Solution:** Implement proper error handling and fallback responses
```python
@mcp.tool()
def book_meeting(lead_id, proposed_time, meeting_type="demo", lead_email=None):
    try:
        # Main logic
        pass
    except Exception as e:
        # Return structured error the agent can handle
        return {
            "confirmed": False,
            "error": str(e),
            "suggestion": "Please try again or contact support"
        }
```

---

## Part 8: Production Deployment

### Checklist for Production MCP Setup

- [ ] MCP server runs on separate process/container
- [ ] Database connection pooling configured for high volume
- [ ] All tools have proper error handling and timeouts
- [ ] Logging configured (see logs in: `mcp_server.log`)
- [ ] Rate limiting on tools (prevent agent abuse)
- [ ] Tool results cached where appropriate
- [ ] Database migrations run before deployment
- [ ] External service dependencies (email, Google Calendar) tested
- [ ] Monitoring/alerting configured for tool failures
- [ ] Agent system prompts updated with tool documentation

### Example: Production-Ready Setup

```python
# mcp_server.py for production
import logging
from logging.handlers import RotatingFileHandler

# Setup logging
handler = RotatingFileHandler('mcp_server.log', maxBytes=10000000, backupCount=5)
logger = logging.getLogger()
logger.addHandler(handler)
logger.setLevel(logging.INFO)

# Database connection pooling
from sqlalchemy.pool import QueuePool
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20
)

# Add tool timeouts
@mcp.tool()
def book_meeting(*args, **kwargs):
    """Tool with timeout protection."""
    import signal
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Tool execution exceeded 30 seconds")
    
    # Set 30-second timeout
    signal.signal(signal.SIGALRM, timeout_handler)
    signal.alarm(30)
    
    try:
        # Tool logic
        pass
    finally:
        signal.alarm(0)  # Disable alarm
```

---

## Quick Reference: MCP vs Main.py

| Aspect | MCP Server (mcp_server.py) | Voice Agent (main.py) |
|--------|---------------------------|----------------------|
| **Purpose** | Expose tools and data | Conduct conversation |
| **Runs** | Constantly (passive) | Per call (active) |
| **Port** | Stdio/HTTP (FastMCP) | WebSocket (Twilio) |
| **Calls** | Agent → MCP | Local or remote |
| **Tools** | Static, reusable | Dynamic per-call state |
| **State** | Minimal (stateless) | Rich (conversation history) |

---

## Summary

1. **MCP = Tools Platform**: Expose business logic as tools
2. **FastMCP = Python Framework**: Easy decorator-based tool definition
3. **Resources = Context**: Read-only data for agent context
4. **Tools = Actions**: Actionable operations (create, update, send)
5. **Agents = Orchestration**: AI systems that call tools intelligently
6. **Rio = Voice Agent**: Mistral LLM with Deepgram input + ElevenLabs output

Start by exploring your `mcp_server.py` - that's your tool platform. Every function decorated with `@mcp.tool()` becomes available to agents like Rio for decision-making and action-taking during calls.

