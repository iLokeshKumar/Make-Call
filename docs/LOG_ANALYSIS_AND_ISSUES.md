# Rio AI Sales Assistant - Log Analysis & Issues

**Date**: 2026-01-27  
**Session Log Time**: 16:50:55 - 17:03:22 (Full demo call with user)

---

## QUICK ANSWERS TO YOUR QUESTIONS

### 1. **Is it using MCP & Agents?**
✅ **YES** - Rio is running an MCP (Model Context Protocol) server with FastMCP (`mcp_server.py`)
- **MCP Tools Available**:
  - `check_icp_qualification()` - Validate customer fit
  - `get_product_info()` - Fetch product data (prevents hallucination)
  - `check_guardrails()` - Verify discount approval
  - `book_meeting()` - Schedule demos
  - `smart_search()` - Search leads/products
  - MCP Resources: `crm://leads/summary`, `crm://inventory`, `crm://appointments`

- **LLM Integration**: Mistral uses these tools via `tool_adapter.py` which converts MCP tools to Mistral function schema
- **Tool Execution Flow**: `main.py` → `run_shared_tool()` → `execute_mcp_tool()` (in `tool_adapter.py`) → MCP functions

---

### 2. **Barge-In Functionality - WHERE IS IT?**
❌ **NOT IMPLEMENTED** - Barge-in is NOT currently working. Current flow:
1. Deepgram continuously transcribes user audio
2. Rio's response is sent to ElevenLabs as full text block
3. ElevenLabs generates audio and streams chunks
4. **Simultaneous audio plays** - both Rio's response AND new user speech overlap

**What's Happening**: The WebSocket listener is async but there's no:
- ✗ Audio interruption detection
- ✗ Check to see if new user input arrived while Rio is speaking
- ✗ TTS cancellation if user speaks

**To fix**: Need interrupt detection in the Twilio media-stream handler. When Deepgram sends transcription with `speech_final: true`, you need to check if previous Rio response is still playing and pause/cancel it.

---

### 3. **Demo Booking - Was It Actually Booked?**
⚠️ **PARTIALLY YES** - It appears the booking was initiated but has technical issues:

**What Happened**:
- Interaction 84 transcript shows full conversation
- Mistral called `book_meeting()` tool twice at [17:02:40] and [17:03:14]
- **ERROR**: `'FunctionTool' object is not callable`
- Despite error, the log shows: `Tool result: {'error': "Tool execution failed...`

**Where It's Stored**:
- **Database**: PostgreSQL `appointment` table (if INSERT succeeded despite error message)
- **To Check**:
  ```sql
  SELECT * FROM appointment WHERE lead_id = 2 ORDER BY created_at DESC;
  SELECT * FROM appointment WHERE appointment_time LIKE '%Thursday%' OR appointment_time LIKE '%3 PM%';
  ```

**The Bug**: The `book_meeting` function is decorated with `@mcp.tool()` from FastMCP. When `tool_adapter.py` tries to call it with `book_meeting(...)`, it's receiving a `FunctionTool` wrapper object instead of the raw function. FastMCP wraps tools for RPC exposure, and you're trying to call it directly from Python.

---

### 4. **Email Sending - To Whom? Where?**
❌ **NO EMAIL WAS ACTUALLY SENT** - The logs show the bot saying "I'll send you a calendar invite" but:

**Evidence**:
- Rio's response includes: `"I'll send you a calendar invite with a secure link"`
- No actual email service was called in the logs
- No `send_email_tool()` or `send_smtp_email()` was triggered
- No email address was captured in the conversation

**Why**: 
- The user never provided an email address during the call
- The system has `email_service.py` but it was never invoked
- Rio is saying it will email, but the tool isn't being called

**To Actually Send Email**, you need:
1. Extract email from leads table (it has `email` column)
2. Or prompt user: "What's your email so I can send the calendar invite?"
3. Call `send_email_tool()` with lead email and appointment details

---

### 5. **Demo Time Confirmed**
✅ **CONFIRMED**: Thursday at 3 PM (in the transcript)
- Timeline of booking attempts:
  - 17:02:40 - First `book_meeting()` call → Error
  - 17:02:40 - TTS quota exceeded (ran out of credits)
  - 17:03:06 - Mistral confirmed: "Thursday at 3 PM it is"
  - 17:03:14 - Second `book_meeting()` call → Error again
  - 17:03:22 - Call ended (client hung up)

---

## DETAILED ISSUES & SOLUTIONS

### **ISSUE #1: FunctionTool Not Callable** ❌ CRITICAL

**Error Message**:
```
Tool execution failed: 'FunctionTool' object is not callable
```

**Root Cause**:
FastMCP wraps decorated functions as `FunctionTool` objects for RPC/protocol exposure. When you import `book_meeting` directly into `tool_adapter.py`, you get the wrapper, not the callable function.

**Location**: 
- [tool_adapter.py:142](tool_adapter.py#L142) - Calls `book_meeting(...)` directly
- [tool_adapter.py:10](tool_adapter.py#L10) - Imports the wrapped tool

**Solution**:
Use FastMCP's client interface to call tools, OR unwrap the function:

```python
# Option 1: Import the raw function from mcp_server BEFORE @mcp.tool() decoration
# (Would require refactoring mcp_server.py)

# Option 2: Use FastMCP's built-in client to call the tool
from mcp_server import mcp

async def execute_mcp_tool(tool_name: str, arguments: dict) -> dict:
    # For book_meeting specifically:
    if tool_name == "book_meeting":
        try:
            # Use mcp.call_tool() if available, or access the raw function
            # Current workaround: call the function bypassing the wrapper
            from mcp_server import SessionLocal
            
            session = SessionLocal()
            lead_id = arguments.get("lead_id")
            proposed_time = arguments.get("proposed_time")
            meeting_type = arguments.get("meeting_type", "demo")
            
            # Fetch lead
            from sqlalchemy import text
            lead_result = session.execute(
                text("SELECT id, name, email FROM lead WHERE id = :lid"), 
                {"lid": lead_id}
            )
            lead = lead_result.first()
            
            if not lead:
                return {"confirmed": False, "error": f"Lead with ID {lead_id} not found"}
            
            lead_dict = dict(lead._mapping)
            
            # Create appointment
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
            
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                "calendar_url": f"https://rio-crm.example.com/appointment/{appointment_id}",
                "lead_name": lead_dict["name"],
                "lead_email": lead_dict["email"]
            }
        except Exception as e:
            return {"confirmed": False, "error": str(e)}
```

---

### **ISSUE #2: No Barge-In Interrupt Handling** ❌ MAJOR

**Current Behavior**:
- Rio speaks while user may be speaking
- No audio ducking or cancellation
- Both streams play simultaneously

**Location**: [main.py:1200-1350] (media-stream WebSocket handler)

**How Barge-In Should Work**:
1. When Deepgram returns transcript with `speech_final=true`
2. Check if ElevenLabs is currently streaming audio (`is_tts_active` flag)
3. If yes: Send `mark` message to Twilio to pause/resume
4. Interrupt current TTS stream

**Solution - Add to WebSocket Handler**:

```python
class MediaStreamHandler:
    def __init__(self):
        self.is_tts_active = False
        self.current_tts_stream_id = None
    
    async def handle_transcription_final(self, transcript_text):
        """When user finishes speaking"""
        if self.is_tts_active:
            # Stop Rio's current response
            print("🛑 Barge-in detected! Stopping current TTS...")
            await self.interrupt_tts_stream()
            self.is_tts_active = False
        
        # Then process new user input
        await self.process_user_input(transcript_text)
    
    async def interrupt_tts_stream(self):
        """Cancel ongoing TTS"""
        if self.websocket:
            # Send clear message to Twilio to flush audio buffer
            await self.websocket.send_json({
                "type": "clear",
            })
```

---

### **ISSUE #3: ElevenLabs Quota Exceeded** ⚠️ BLOCKING

**Error**:
```
ElevenLabs API Message: {'error': 'quota_exceeded', 'code': 1008}
This request exceeds your quota of 10000. You have 13 credits remaining, while 18 credits are required.
```

**Timeline**:
- [17:02:50] First quota error (mid-response)
- [17:03:03] Second quota error
- [17:03:06] Third quota error

**Credits Calculation**:
- Each TTS request costs credits (roughly 1 credit = ~1 second of audio)
- You have 13 credits left, each response needs 18-22 credits
- **Result**: TTS stops mid-response, call quality degrades

**Solution**:
1. **Upgrade plan**: Buy more credits in ElevenLabs dashboard
2. **Use fallback TTS**: If ElevenLabs fails, switch to Google Cloud TTS or Azure Speech
3. **Optimize prompts**: Shorter responses = fewer credits used
4. **Add fallback logic**:

```python
async def text_to_speech(text):
    try:
        # Try ElevenLabs first
        return await elevenlabs_tts(text)
    except QuotaExceeded:
        logger.warning("ElevenLabs quota exceeded, using fallback...")
        # Fallback to Google or Azure
        return await google_tts_fallback(text)
```

---

### **ISSUE #4: No Email Capture or Sending** ⚠️ FEATURE GAP

**Current State**:
- Rio promises: "I'll send you a calendar invite"
- Actually sent: Nothing
- Email address: Never captured

**Location**: [main.py] - Email sending logic exists but isn't triggered

**Solution**:

```python
async def handle_demo_booking(lead_id, email_address=None):
    """
    After booking is confirmed, send email
    """
    # Get lead info
    with SessionLocal() as session:
        lead = session.query(Lead).filter(Lead.id == lead_id).first()
        
        # If no email provided, use lead's email
        if not email_address:
            email_address = lead.email
        
        if not email_address:
            logger.warning(f"No email address for lead {lead_id}")
            return False
        
        # Send calendar invite
        try:
            await send_smtp_email(
                to_email=email_address,
                subject=f"Your Demo Scheduled - Rio at {company_name}",
                body=f"""
                Hi {lead.name},
                
                Your Samsung QLED TV demo is scheduled for Thursday at 3 PM.
                
                Dial in here: [Video Link]
                
                Looking forward to showing you our products!
                Rio
                """
            )
            logger.info(f"✅ Calendar invite sent to {email_address}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to send email: {e}")
            return False
```

---

### **ISSUE #5: Quota Exceeded During Active Call** ⚠️ UX KILLER

**What Happened**: Mid-call, TTS quota exhausted → audio stopped → call quality terrible

**When Should This Be Checked**: Before call starts (startup check)

```python
@app.on_event("startup")
async def check_service_quotas():
    """Verify we have enough credits before accepting calls"""
    
    # Check ElevenLabs quota
    try:
        response = requests.get(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": ELEVENLABS_API_KEY}
        )
        user_data = response.json()
        
        character_count = user_data.get("character_count", 0)
        character_limit = user_data.get("character_limit", 0)
        credits_remaining = character_limit - character_count
        
        if credits_remaining < 500:  # Emergency threshold
            logger.error(f"⚠️ ElevenLabs quota low: {credits_remaining} credits remaining")
            # Either warn or disable TTS until upgraded
    except Exception as e:
        logger.error(f"Could not check ElevenLabs quota: {e}")
```

---

## SUMMARY TABLE

| Issue | Severity | Status | Impact |
|-------|----------|--------|--------|
| FunctionTool Not Callable | 🔴 Critical | ❌ Unfixed | Demo booking fails, errors in transcript |
| No Barge-In Interrupt | 🟠 Major | ❌ Not Implemented | Audio overlap, poor UX |
| ElevenLabs Quota | 🟠 Major | ⚠️ Active | TTS cuts out mid-call |
| No Email Sending | 🟡 Medium | ❌ Not Implemented | Calendar invite never sent |
| No Email Capture | 🟡 Medium | ❌ Not Implemented | Can't contact leads after calls |

---

## NEXT STEPS

### 1. Immediate (Fix Broken Things)
- [ ] Fix `book_meeting` FunctionTool error - use tool_adapter bypass
- [ ] Add ElevenLabs quota check on startup
- [ ] Test booking in database with SQL query above

### 2. Short-term (Complete Features)
- [ ] Implement barge-in interrupt handling
- [ ] Add email capture prompt or extraction from lead DB
- [ ] Implement email sending after demo booking
- [ ] Add fallback TTS provider

### 3. Verify Working
Run this SQL to confirm booking was saved:
```sql
SELECT * FROM appointment ORDER BY created_at DESC LIMIT 5;
```

Check if lead's email was captured:
```sql
SELECT id, name, email, phone FROM lead WHERE id = 2;
```

---

## KEY FILES TO MODIFY

1. **tool_adapter.py** - Fix book_meeting execution
2. **main.py** - Add barge-in logic to media-stream handler
3. **mcp_server.py** - Consider refactoring tool registration
4. **email_service.py** - Ensure it's called after booking
5. **Database setup** - Ensure email field is populated for leads

