# Visual Guide: MCP vs Agents vs System Behaviors

## Simple Diagram: The Three Concepts

```
┌─────────────────────────────────────────────────────────────┐
│                    RIO SALES ASSISTANT                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │            LLM (Mistral) - Makes Decisions           │  │
│  │     "Should I book? Should I check ICP?"             │  │
│  └────────────────────┬─────────────────────────────────┘  │
│                       │                                     │
│                       ├─ "I'll book_meeting()"  ← MCP Tool  │
│                       ├─ "I'll check_icp()"     ← MCP Tool  │
│                       ├─ "I'll get_product()"   ← MCP Tool  │
│                       │                                     │
│  MCP TOOLS (LLM chooses what to do):                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  book_meeting()        ✅ Tool                        │  │
│  │  check_icp()           ✅ Tool                        │  │
│  │  get_product_info()    ✅ Tool                        │  │
│  │  check_guardrails()    ✅ Tool                        │  │
│  └──────────────────────────────────────────────────────┘  │
│                       │                                     │
│  SYSTEM BEHAVIORS (Always running, no LLM choice):        │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  Listen for user speech      ✅ Always on             │  │
│  │  Detect barge-in             ✅ Always watching      │  │
│  │  Stream to Deepgram          ✅ Always on             │  │
│  │  Stream from ElevenLabs      ✅ Always on             │  │
│  │  WebSocket management        ✅ Always running       │  │
│  └──────────────────────────────────────────────────────┘  │
│                       │                                     │
│  INFRASTRUCTURE (Utilities - not exposed):                 │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  send_smtp_email()                                   │  │
│  │  database_query()                                    │  │
│  │  log_interaction()                                   │  │
│  │  convert_to_html()                                   │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## Call Flow with Annotations

```
USER CALLS RIO
    ↓
SYSTEM BEHAVIOR: WebSocket connection established
    ↓
SYSTEM BEHAVIOR: Start listening (Deepgram streaming)
    ↓
Rio: "Hi! What can I help with?"
    ↓
SYSTEM BEHAVIOR: Stream to ElevenLabs, play audio
    ↓
SYSTEM BEHAVIOR: Listen for user speech (Deepgram)
    ↓
User: "I want to see your products"
    ↓
SYSTEM BEHAVIOR: Transcribe (Deepgram)
    ↓
    ┌─────────────────────────────────┐
    │  LLM DECISION POINT (Mistral)   │
    │  "Should I use a tool?"          │
    ├─────────────────────────────────┤
    │  ✅ YES - Use get_product_info() │ ← MCP TOOL
    └─────────────────────────────────┘
    ↓
MCP TOOL EXECUTION: get_product_info("products")
    → Query database
    → Get real pricing
    → Return {name, price, features}
    ↓
Rio: "Here are our products..." [includes real data]
    ↓
SYSTEM BEHAVIOR: Stream response to ElevenLabs
    ↓
SYSTEM BEHAVIOR: Play audio to user
    ↓
SYSTEM BEHAVIOR: Continue listening (barge-in check)
    ↓
User: "I want to book a demo" (user speaks while Rio is speaking!)
    ↓
SYSTEM BEHAVIOR: Detect barge-in (user_audio + rio_speaking)
    ↓
SYSTEM BEHAVIOR: Stop Rio's audio immediately
    ↓
SYSTEM BEHAVIOR: Listen to user instead
    ↓
Mistral gets new input
    ↓
    ┌─────────────────────────────────┐
    │  LLM DECISION POINT (Mistral)   │
    │  "User wants to book"            │
    ├─────────────────────────────────┤
    │  ✅ YES - Use book_meeting()    │ ← MCP TOOL
    └─────────────────────────────────┘
    ↓
MCP TOOL EXECUTION: book_meeting(lead_id=2, time="Tuesday 3PM", type="demo")
    → Fetch lead from DB
    → Create appointment
    → Send confirmation email to lead
    → Return {confirmed: true, appointment_id: 123, email_sent: true}
    ↓
Rio: "Perfect! Demo scheduled for Tuesday at 3 PM. I sent you a calendar invite!"
    ↓
SYSTEM BEHAVIOR: Stream response
    ↓
SYSTEM BEHAVIOR: Continue waiting for user (barge-in still active)
```

---

## When Each Component is Used

### MCP Tools Timeline

```
Timeline: One call with Rio

        ↑
        │
        │  ┌─ check_icp_qualification() → Qualify lead
        │  │
        │  ├─ get_product_info() → Answer questions
        │  │
        │  ├─ book_meeting() → Create appointment
        │  │
        │  └─ send_followup_email() → Send details
        │
───────────────────────────────→ TIME
```

### System Behaviors Timeline

```
Timeline: One call with Rio

        ↑
        │  ALWAYS RUNNING ← System Behaviors
        │  ├─ Listening (Deepgram)
        │  ├─ Checking for barge-in
        │  ├─ Streaming TTS (ElevenLabs)
        │  ├─ WebSocket management
        │  └─ Audio buffering
        │
───────────────────────────────→ TIME
        Entire call duration
```

---

## The Difference Illustrated

### MCP Tool Example: book_meeting()

```
┌──────────────────────────────────────────────┐
│           Mistral LLM (AI Decision)          │
├──────────────────────────────────────────────┤
│                                              │
│  "User wants to book. I'll use book_meeting" │
│                                              │
└────────────────────┬─────────────────────────┘
                     │
                     │ CALLS TOOL
                     ↓
          ┌─────────────────────────┐
          │  book_meeting()         │
          │  (MCP Tool)             │
          ├─────────────────────────┤
          │ 1. Fetch lead           │
          │ 2. Create appointment   │
          │ 3. Send email           │
          │ 4. Return result        │
          └─────────────────────────┘
                     │
                     │ RETURNS RESULT
                     ↓
          ┌─────────────────────────┐
          │ {confirmed: true,       │
          │  appointment_id: 123,   │
          │  email_sent: true}      │
          └─────────────────────────┘
                     │
                     │ CONTINUES CONVERSATION
                     ↓
    Rio: "Demo scheduled! Check your email"
```

### System Behavior Example: Barge-In

```
┌──────────────────────────────────────────────┐
│         Rio is Speaking (ElevenLabs)        │
│         User is Speaking (Deepgram)         │
│                                              │
│    → System AUTOMATICALLY detects both      │
│                                              │
└────────────────────┬─────────────────────────┘
                     │
              NO LLM INVOLVED!
                     │
                     ↓
    ┌──────────────────────────────┐
    │  Barge-In Detection          │
    │  (System Behavior)           │
    ├──────────────────────────────┤
    │  IF rio_speaking AND         │
    │     user_speaking:           │
    │      1. Stop Rio             │
    │      2. Listen to user       │
    │      3. Send to Mistral      │
    │  ENDIF                       │
    └──────────────────────────────┘
                     │
              NO RETURN VALUE NEEDED!
                     │
                     ↓
         User speech processed normally
```

---

## Decision Tree: What Should This Be?

```
                    START
                      │
                      ↓
        ╔═══════════════════════════════╗
        ║ Does the LLM CHOOSE to use   ║
        ║      this in conversation?   ║
        ╚═════════┬═══════════════════╝
                  │
          ┌───────┴────────┐
          │                │
         YES              NO
          │                │
          ↓                ↓
    ┌──────────┐   ┌─────────────────┐
    │ MCP TOOL │   │ Should it ALWAYS│
    │          │   │ be running?     │
    │Examples: │   └────┬────────┬───┘
    │ • book   │        │        │
    │ • check  │       YES      NO
    │ • get    │        │        │
    └──────────┘        ↓        ↓
                    ┌────────┐ ┌─────────┐
                    │BEHAVIOR│ │UTILITY  │
                    │        │ │FUNCTION │
                    │Always  │ │         │
                    │on      │ │Helper   │
                    │        │ │only     │
                    └────────┘ └─────────┘
```

---

## Your Barge-In Situation

### ❌ If it was an MCP Tool:

```
                ┌──────────────┐
                │ Mistral LLM  │
                └────────┬─────┘
                         │
                         ↓
           "Should I call enable_barge_in()?"
                         │
    ┌────────────────────┴────────────────────┐
    │  But wait... LLM doesn't KNOW          │
    │  that user is interrupting!             │
    │                                         │
    │  The LLM can't make this decision!     │
    │  Makes no sense as a tool.              │
    └─────────────────────────────────────────┘

         This is WRONG ❌
```

### ✅ If it's a System Behavior:

```
              ┌─────────────────┐
              │ System SEES:    │
              │ • Rio speaking  │
              │ • User speaking │
              │ (Both at once!) │
              └────────┬────────┘
                       │
                       ↓
        System AUTOMATICALLY:
        1. Stops Rio's audio
        2. Listens to user
        3. Sends to Mistral
        4. No tool call needed!
                       │
        This is RIGHT ✅
```

---

## Architecture for Rio

### MCP Layer (What LLM chooses)
```
mcp_server.py:

@mcp.tool()
def book_meeting(lead_id, time, type):
    # LLM chooses when to call this
    pass

@mcp.tool()
def check_icp_qualification(size, industry, employees):
    # LLM chooses when to call this
    pass

@mcp.tool()
def get_product_info(product):
    # LLM chooses when to call this
    pass
```

### System Behavior Layer (Always running)
```
main.py:

async def websocket_endpoint(websocket, lead_id):
    while True:
        # ALWAYS listening
        if detect_user_audio():
            # Check for barge-in
            if rio_speaking and user_speaking:
                stop_rio()  # AUTOMATIC
        
        # ALWAYS streaming
        stream_to_deepgram()
        stream_from_elevenlabs()
```

---

## The Key Principle

```
┌─────────────────────────────────────────┐
│   MCP TOOLS = "Can I do this?"         │
│   (LLM makes the choice)                │
│                                         │
│   SYSTEM BEHAVIORS = "I'm doing this"  │
│   (System does it automatically)        │
│                                         │
│   For Barge-In:                        │
│   → NOT a choice                        │
│   → NOT something LLM calls             │
│   → SYSTEM automatically detects        │
│   → Therefore: SYSTEM BEHAVIOR ✅      │
└─────────────────────────────────────────┘
```

---

## Answers to Your Questions

### Q: "Is barge-in an MCP/agent or something else?"

**A:** Barge-in is a **SYSTEM BEHAVIOR**
- Not an MCP tool (LLM doesn't choose it)
- Not an agent (doesn't make autonomous decisions)
- It's infrastructure (part of how WebSocket handler works)

### Q: "How to decide?"

**A:** Ask yourself:
- "Does the LLM decide when to use this?" 
  - YES → MCP Tool
  - NO → Continue...
- "Should this always be happening?"
  - YES → System Behavior
  - NO → Utility function

### Q: "Is that dummy link or real?"

**A:** ✅ **UPDATED to real Google Meet**
- Old: `https://rio-demo.example.com/join` (dummy)
- New: `https://meet.google.com/new` (real - creates actual meeting)

User clicks → Gets real Google Meet room → Can join from browser

Done! Any other questions? 🎯
