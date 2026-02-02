# MCP vs Agents - Comprehensive Guide

## Quick Definition

### **MCP Tools** (What the LLM can call)
```
Function the LLM can CHOOSE to invoke during conversation
- Clear input/output
- Deterministic behavior
- Returns data to LLM
- LLM decides IF and WHEN to use it

Example: book_meeting(lead_id, time, type)
→ LLM: "User wants to book a demo, I should call book_meeting"
```

### **Agents** (How the system OPERATES autonomously)
```
Autonomous workflow that makes decisions and takes actions
- Runs independently, not called by LLM
- Can chain multiple tools together
- Makes plans and adjusts based on results
- Loops until goal achieved

Example: "Lead Qualification Agent"
→ Runs autonomously: Ask questions → Check ICP → Book meeting → Send email
```

### **System Behaviors** (Infrastructure, not business logic)
```
How the system behaves at the technical level
- Not called by LLM
- Not a tool the LLM chooses
- Built into the application flow
- Handles user interaction patterns

Example: Barge-in (user interrupts Rio)
```

---

## Decision Tree: What Should This Be?

```
START
  ↓
  Q: Does the LLM CHOOSE to use this during conversation?
  │
  ├─ YES → Is it a single atomic action? 
  │         ├─ YES → MCP TOOL ✅
  │         └─ NO → Might need Agent wrapper
  │
  └─ NO → Is this how the system OPERATES?
          ├─ YES → SYSTEM BEHAVIOR (Infrastructure)
          └─ NO → Probably an Agent
```

---

## Real-World Examples from Rio

### ✅ These are MCP TOOLS (LLM Chooses)

**1. book_meeting(lead_id, time, type)**
- LLM decides: "User wants to book, I should call this"
- Atomic action: Create appointment + Send email
- Returns confirmation to LLM
- LLM continues conversation

**2. check_icp_qualification(company_size, industry, employees)**
- LLM decides: "Need to qualify this lead first"
- Returns: ICP score + recommendation
- LLM uses result to decide next steps

**3. get_product_info(product_name)**
- LLM decides: "User asked about pricing, I need actual data"
- Returns: Product details from database
- LLM includes in response

**4. check_guardrails(discount_percent)**
- LLM decides: "User asked for discount, I need to check policy"
- Returns: Approved/rejected + max allowed
- LLM tells user the result

### ❌ These are NOT MCP TOOLS

**1. "listen_for_speech"** - This isn't a tool!
- Not something the LLM chooses to do
- Happens automatically in the WebSocket handler
- Part of the system's core behavior

**2. "speak_audio"** - This isn't a tool either!
- LLM generates text, system automatically converts to speech
- Not a choice the LLM makes
- Infrastructure

---

## The MCP Tool Pattern

```python
@mcp.tool()
def book_meeting(lead_id: int, proposed_time: str, meeting_type: str = "demo") -> dict:
    """
    This is an MCP Tool because:
    
    1. ✅ LLM CHOOSES to call it
       "I'll use book_meeting to schedule this demo"
    
    2. ✅ DETERMINISTIC
       Given same inputs → always same behavior
    
    3. ✅ CLEAR INPUT/OUTPUT
       Input: lead_id, time, type
       Output: {confirmed: bool, appointment_id: int, email_sent: bool}
    
    4. ✅ ATOMIC UNIT
       Does one complete thing: Book a meeting
       Includes side effects (email) as part of that one thing
    
    5. ✅ LLM UNDERSTANDS RESULT
       Tool returns data/status that LLM can interpret and continue conversation
    """
    
    # Complete workflow:
    # 1. Fetch lead
    # 2. Create appointment
    # 3. Send email
    # 4. Return result
    
    return {
        "confirmed": True,
        "appointment_id": 123,
        "email_sent": True,
        "message": "Demo scheduled!"
    }
```

---

## System Behaviors vs Tools

### ❌ WRONG: Making barge-in a tool

```python
@mcp.tool()
def handle_barge_in() -> dict:
    """Enable barge-in interruption"""
    # This is WRONG because:
    # - LLM would need to CHOOSE to call it
    # - But barge-in should ALWAYS be on
    # - Not a choice, it's automatic behavior
```

### ✅ RIGHT: Barge-in as system behavior

```python
# In main.py WebSocket handler
async def websocket_endpoint(websocket: WebSocket, lead_id: int):
    session = CallSession()
    
    while True:
        message = await websocket.receive_text()
        
        # AUTOMATIC: Check if user is speaking while Rio speaks
        if user_is_speaking and rio_is_speaking:
            # INTERRUPT: Stop Rio, listen to user
            await stop_rio_speaking()
            await listen_to_user()
        
        # This is ALWAYS ON, not a choice
```

---

## When to Create an Agent (Advanced)

### Definition
An **Agent** is a workflow that makes sequential decisions, using multiple tools.

### Example: Lead Qualification Agent

**NOT a tool** because:
- Has multiple steps
- Makes decisions based on results
- Adjusts behavior based on outcomes
- Runs a loop

```python
class LeadQualificationAgent:
    """
    Autonomous workflow that:
    1. Asks questions
    2. Checks ICP
    3. If qualified → offer demo
    4. If not qualified → add to nurture list
    """
    
    async def run(self, lead_id: int):
        # Step 1: Understand company
        questions = await ask_about_company()
        
        # Step 2: Check if they qualify
        icp_result = await check_icp_qualification(
            company_size=questions["size"],
            industry=questions["industry"],
            employees=questions["count"]
        )
        
        # Step 3: Decide what to do
        if icp_result["qualified"]:
            await book_meeting(lead_id, "next available")
        else:
            await add_to_nurture_sequence(lead_id)
```

**For Rio:** You probably don't need agents yet. Your LLM-based system already IS agent-like through Mistral's function calling.

---

## Decision Guide: MCP Tool vs System Behavior

| Question | MCP Tool | System Behavior |
|----------|----------|-----------------|
| **Does LLM choose when to use this?** | YES ✅ | NO ❌ |
| **Is it a single atomic action?** | YES ✅ | Varies |
| **Can LLM understand the result?** | YES ✅ | N/A |
| **Should it ALWAYS be on?** | NO | YES ✅ |
| **Example** | book_meeting | Barge-in listening |

---

## For Rio: What Goes Where

### ✅ MCP Tools (in mcp_server.py)
```
book_meeting()
check_icp_qualification()
get_product_info()
check_guardrails()
Any future business logic that LLM should choose
```

### ✅ System Behaviors (in main.py)
```
Barge-in detection and handling
Speech-to-text streaming setup
Text-to-speech streaming output
Audio buffer management
WebSocket connection handling
```

### ✅ Infrastructure (utility functions)
```
send_smtp_email()
Database transactions
Logging
Error handling
```

---

## Barge-In Specifically

### What is Barge-In?
User speaking while Rio is speaking → Rio should STOP and LISTEN

### Why NOT an MCP Tool?
```python
# ❌ WRONG - Making it a tool
@mcp.tool()
def handle_barge_in() -> dict:
    """Hmm, when would the LLM call this?"""
    pass

# The LLM can't decide when to call handle_barge_in
# It doesn't KNOW the user is speaking over it
# It needs to happen automatically
```

### Why it's System Behavior
```python
# ✅ RIGHT - System behavior
async def websocket_endpoint(websocket: WebSocket, lead_id: int):
    session = CallSession()
    session.is_rio_speaking = False
    
    while True:
        message = await websocket.receive_text()
        
        # AUTOMATIC: Detect when user speaks
        if message["event"] == "media":
            user_audio = extract_audio(message)
            
            # AUTOMATIC: If Rio is speaking, interrupt
            if session.is_rio_speaking and is_significant_speech(user_audio):
                await session.stop_rio_tts()
                session.is_rio_speaking = False
                
                # Now listen to user
                transcript = await transcribe_user_audio(user_audio)
                
                # Now SEND to Mistral for response
                await send_to_mistral(transcript)
        
        # This ALWAYS watches for user speech
        # No "enable barge-in" tool needed
```

---

## Flow Diagram for Rio

```
CALL STARTS
    ↓
┌─────────────────────────────────────────┐
│ SYSTEM BEHAVIORS (Always Running)       │
├─────────────────────────────────────────┤
│ • Listen for user speech (WebSocket)    │
│ • Detect barge-in interruption          │
│ • Stream audio to/from Deepgram         │
│ • Stream audio to/from ElevenLabs       │
│ • Handle connection lifecycle           │
└──────────┬──────────────────────────────┘
           ↓
User: "I'd like to see a demo"
           ↓
┌─────────────────────────────────────────┐
│ LLM (Mistral) CHOOSES TOOLS             │
├─────────────────────────────────────────┤
│ 1. check_icp_qualification()  ← MCP Tool│
│    "Let me verify they're qualified"    │
│                                         │
│ 2. book_meeting()  ← MCP Tool           │
│    "Great! Let me book the demo"        │
│                                         │
│ Mistral gets results and responds       │
└─────────────────────────────────────────┘
           ↓
Rio: "Demo scheduled for Tuesday!"
           ↓
┌─────────────────────────────────────────┐
│ SYSTEM BEHAVIORS (Still Always Running) │
├─────────────────────────────────────────┤
│ • Convert text to speech (ElevenLabs)   │
│ • Stream audio to user                  │
│ • Continue listening for interruption   │
│ • If user speaks → barge-in handling    │
└─────────────────────────────────────────┘
```

---

## Summary: How to Decide

```
┌─ Does the LLM CHOOSE to use this? ─┐
│                                    │
├─ YES → MCP TOOL                   │
│        (book_meeting, etc.)        │
│                                    │
└─ NO ─────┬──────────────────────────┘
           │
           ├─ Should it ALWAYS be on?
           │  ├─ YES → SYSTEM BEHAVIOR
           │  │        (Barge-in, listening)
           │  │
           │  └─ NO → Helper function
           │          (send_email, etc.)
```

---

## Key Insight

**Tools are what the LLM can DO.
Behaviors are how the system ACTS.
Infrastructure is how it all WORKS.**

- **MCP Tool**: "Can I book a meeting?" → YES/NO
- **System Behavior**: "Is user interrupting?" → Handle automatically
- **Infrastructure**: "How do we send emails?" → Internal detail

For Rio, think about it this way:
- Tools: "What CHOICES does the LLM have?"
- Behaviors: "What does the system DO without being asked?"
