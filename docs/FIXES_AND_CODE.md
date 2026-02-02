# IMMEDIATE FIXES - Code Solutions

## FIX #1: Book Meeting Tool Error

**File**: `tool_adapter.py`  
**Lines**: 142-147  
**Problem**: `book_meeting` is a FastMCP wrapped object, not callable directly

### Current Code (BROKEN):
```python
elif tool_name == "book_meeting":
    return book_meeting(
        lead_id=arguments.get("lead_id"),
        proposed_time=arguments.get("proposed_time"),
        meeting_type=arguments.get("meeting_type", "demo")
    )
```

### Fixed Code:
```python
elif tool_name == "book_meeting":
    # ✅ FIXED: Bypass MCP wrapper, call DB directly
    from database import SessionLocal
    from sqlalchemy import text
    
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
            lead = lead_result.first()
            
            if not lead:
                return {
                    "confirmed": False,
                    "error": f"Lead with ID {lead_id} not found"
                }
            
            lead_dict = dict(lead._mapping)
            
            # Create appointment
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
            
            return {
                "confirmed": True,
                "appointment_id": appointment_id,
                "lead_name": lead_dict["name"],
                "lead_email": lead_dict["email"],
                "message": f"Demo scheduled for {lead_dict['name']} on {proposed_time}"
            }
        except Exception as e:
            logger.error(f"Failed to book meeting: {e}")
            return {
                "confirmed": False,
                "error": f"Failed to book meeting: {str(e)}"
            }
```

---

## FIX #2: Send Email After Booking

**File**: `main.py`  
**Location**: After successful `book_meeting()` execution (around line 1114)

### Add This Code:

```python
async def send_booking_email(lead_email: str, lead_name: str, appointment_time: str):
    """Send calendar invite email after demo is booked"""
    try:
        email_subject = f"Your Demo Scheduled - Rio Sales Assistant"
        
        email_body = f"""
        <h2>Your Demo is Scheduled!</h2>
        
        <p>Hi {lead_name},</p>
        
        <p>Great news! Your Samsung QLED TV demo has been confirmed for:</p>
        
        <p><strong>{appointment_time}</strong></p>
        
        <p>
            <a href="https://meet.google.com/new">
                Join Demo Video Call
            </a>
        </p>
        
        <p>If you need to reschedule, just let me know!</p>
        
        <p>Looking forward to showing you our products,<br/>
        Rio<br/>
        Digital Sales Assistant</p>
        """
        
        await send_smtp_email(
            to_email=lead_email,
            subject=email_subject,
            body=email_body
        )
        logger.info(f"✅ Calendar email sent to {lead_email}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to send booking email: {e}")
        return False

# Then, in your Mistral tool executor, after book_meeting succeeds:
if tool_result.get("confirmed"):
    # Send follow-up email
    await send_booking_email(
        lead_email=tool_result.get("lead_email"),
        lead_name=tool_result.get("lead_name"),
        appointment_time=arguments.get("proposed_time")
    )
```

---

## FIX #3: Add Barge-In Interrupt Handling

**File**: `main.py`  
**Location**: WebSocket media-stream handler (around line 1200)

### Current Flow (No Interruption):
```python
async def websocket_endpoint(websocket: WebSocket, lead_id: int):
    # Simultaneous audio - no interruption handling
    # Rio keeps speaking even if user speaks
```

### Fixed Flow with Barge-In:

```python
class CallSession:
    """Track state for each call"""
    def __init__(self):
        self.is_rio_speaking = False
        self.current_message_id = None
        self.websocket = None

async def handle_user_transcription_final(session: CallSession, transcript_text: str):
    """Called when user finishes a phrase"""
    
    # Check if Rio is currently speaking
    if session.is_rio_speaking:
        logger.info("🛑 Barge-in detected! Stopping Rio's response...")
        
        # Send signal to Twilio to clear audio buffer
        await session.websocket.send_json({
            "type": "clear",  # Clears the audio buffer
        })
        
        # Mark Rio as no longer speaking
        session.is_rio_speaking = False
    
    # Now process the user's new input
    logger.info(f"📝 Processing user input: {transcript_text}")
    
    # Continue with Mistral + TTS
    ...

async def set_rio_speaking_status(session: CallSession, is_speaking: bool):
    """Track when Rio starts/stops speaking"""
    session.is_rio_speaking = is_speaking
    if is_speaking:
        logger.info("🎤 Rio starts speaking...")
    else:
        logger.info("🔇 Rio stops speaking...")

# Usage in media-stream handler:
async def websocket_endpoint(websocket: WebSocket, lead_id: int):
    session = CallSession()
    session.websocket = websocket
    
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            
            if message["event"] == "media" and message.get("media", {}).get("payload"):
                # Audio received from user
                ...
            
            elif message.get("type") == "final":
                # User finished speaking
                transcript = message.get("transcript", "")
                
                # Check for barge-in
                await handle_user_transcription_final(session, transcript)
                
                # Rio starts responding
                await set_rio_speaking_status(session, True)
                
                # Get Mistral response + TTS
                response = await mistral.get_response(transcript)
                
                # Stream TTS audio
                await stream_tts_audio(session, response)
                
                # Rio stops speaking
                await set_rio_speaking_status(session, False)
    
    except WebSocketDisconnect:
        logger.info("Call disconnected")
```

---

## FIX #4: Check TTS Quota Before Accepting Call

**File**: `main.py`  
**Location**: Startup event or call initialization

### Add Quota Check:

```python
@app.on_event("startup")
async def verify_elevenlabs_balance():
    """Check TTS credits before accepting calls"""
    try:
        headers = {"xi-api-key": os.getenv("ELEVENLABS_API_KEY")}
        
        response = requests.get(
            "https://api.elevenlabs.io/v1/user",
            headers=headers,
            timeout=5
        )
        
        if response.status_code != 200:
            logger.warning(f"Could not verify ElevenLabs balance: {response.status_code}")
            return
        
        user_data = response.json()
        character_count = user_data.get("character_count", 0)
        character_limit = user_data.get("character_limit", 0)
        credits_remaining = character_limit - character_count
        
        logger.info(f"ElevenLabs Balance: {credits_remaining}/{character_limit} credits")
        
        # Set thresholds
        CRITICAL_THRESHOLD = 50      # Less than 50 = block new calls
        WARNING_THRESHOLD = 200       # Less than 200 = warn in logs
        
        if credits_remaining < CRITICAL_THRESHOLD:
            logger.error("🚨 CRITICAL: ElevenLabs credits critically low!")
            logger.error(f"   {credits_remaining} credits remaining")
            logger.error("   New calls will fail with audio cutouts")
            # Option: Disable accepting new calls
            app.state.tts_available = False
        elif credits_remaining < WARNING_THRESHOLD:
            logger.warning(f"⚠️  WARNING: ElevenLabs credits low ({credits_remaining} remaining)")
            # Option: Only accept high-priority calls
            app.state.tts_available = True
        else:
            logger.info(f"✅ TTS service available")
            app.state.tts_available = True
    
    except Exception as e:
        logger.error(f"Error checking ElevenLabs balance: {e}")

# Then in your call endpoint:
@app.post("/make-call")
async def make_call(to: str, lead_id: int):
    if not app.state.tts_available:
        raise HTTPException(
            status_code=503,
            detail="TTS service unavailable - insufficient credits"
        )
    
    # Proceed with call
    ...
```

---

## FIX #5: Update Mistral Tool Calling

**File**: `main.py`  
**Location**: Where tool results are processed (around line 1114-1120)

### Current Code (Missing Email):
```python
result = await execute_mcp_tool(name, args)
logger.info(f"📋 [MCP] Tool result: {result}")
```

### Fixed Code (With Email):
```python
result = await execute_mcp_tool(name, args)
logger.info(f"📋 [MCP] Tool result: {result}")

# NEW: Check if booking succeeded, then send email
if name == "book_meeting" and result.get("confirmed"):
    lead_email = result.get("lead_email")
    lead_name = result.get("lead_name")
    appointment_time = args.get("proposed_time")
    
    if lead_email:
        try:
            email_sent = await send_booking_email(
                lead_email=lead_email,
                lead_name=lead_name,
                appointment_time=appointment_time
            )
            if email_sent:
                logger.info(f"✅ Sent calendar invite to {lead_email}")
            else:
                logger.warning(f"⚠️  Calendar invite failed to send")
        except Exception as e:
            logger.error(f"Error sending booking email: {e}")
    else:
        logger.warning("No email address available for booking confirmation")
```

---

## TEST CHECKLIST

After applying all fixes:

### ✅ Test 1: Demo Booking
```sql
-- Make a test call and book demo
SELECT COUNT(*) FROM appointment WHERE lead_id = 2;
-- Expected: 1 or more (was 0 before)
```

### ✅ Test 2: Email Sending
```
- Make a test call with a real email
- Check inbox for calendar invite
- Verify link works
```

### ✅ Test 3: Barge-In
```
- Call Rio
- While Rio is speaking, say something
- Rio should pause and listen to you
- (Verify in logs: "🛑 Barge-in detected!")
```

### ✅ Test 4: Audio Quality
```
- Make several calls in sequence
- Check ElevenLabs credit balance
- Verify no quota errors in logs
```

### ✅ Test 5: Full Flow
```
1. User calls → Rio picks up
2. Rio asks qualifying questions
3. User agrees to demo
4. Rio books demo → SAVES TO DB ✅
5. Lead receives email ✅
6. If user speaks, Rio listens ✅
```

---

## DEPLOYMENT ORDER

1. **First**: Fix book_meeting (tool_adapter.py) - Most critical
2. **Second**: Add email sending (main.py) - Second priority
3. **Third**: Add barge-in logic (main.py) - UX improvement
4. **Fourth**: Add quota check (main.py) - Preventive

Each fix can be deployed independently. **Recommend deploying all 4 before resuming production calls.**

