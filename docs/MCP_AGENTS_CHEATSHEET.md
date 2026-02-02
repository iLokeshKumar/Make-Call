# MCP vs AGENTS - CHEAT SHEET

## The Difference in One Sentence

```
MCP Tool    = What the LLM can CHOOSE to do
Agent       = What the system does on its OWN
Behavior    = How the system AUTOMATICALLY works
```

---

## For Rio - Concrete Examples

### ✅ This is an MCP TOOL
```
LLM: "User wants to book, I'll call book_meeting()"
→ Tool executes
→ Appointment created
→ Email sent
→ Result returned to LLM
→ LLM continues talking
```

### ❌ This is NOT an MCP TOOL (It's Behavior)
```
User: "I want to book" (speaking over Rio)
↓
System AUTOMATICALLY:
  1. Detects user audio (barge-in)
  2. Stops Rio speaking
  3. Listens to user
  4. Sends to Mistral

No tool call needed - system just does it!
```

---

## Quick Decision

| Question | Answer | Type |
|----------|--------|------|
| "Does the LLM CHOOSE to use this?" | YES | MCP Tool ✅ |
| "Does the LLM CHOOSE to use this?" | NO | Continue... |
| "Should this ALWAYS be running?" | YES | System Behavior ✅ |
| "Should this ALWAYS be running?" | NO | Utility function |

---

## For Barge-In Specifically

**Is it an MCP Tool?** NO ❌
**Is it an Agent?** NO ❌
**What is it?** SYSTEM BEHAVIOR ✅

**Why?**
- LLM doesn't decide to "enable barge-in"
- It's always listening automatically
- System detects & handles interruption
- No choice needed - just infrastructure

---

## Google Meet Link

✅ **Real link (not dummy):**
```
https://meet.google.com/new
```

When user clicks: Creates actual Google Meet room

---

## Rio's Architecture

```
MCP TOOLS (LLM chooses):
├─ book_meeting()
├─ check_icp_qualification()  
├─ get_product_info()
└─ check_guardrails()

SYSTEM BEHAVIORS (Always on):
├─ Barge-in detection
├─ Deepgram streaming (speech-to-text)
├─ ElevenLabs streaming (text-to-speech)
└─ WebSocket connection handling

INFRASTRUCTURE (Helpers):
├─ send_smtp_email()
├─ database functions
└─ logging utilities
```

---

## Implementation

```
MCP Tools go in:
  mcp_server.py
  with @mcp.tool() decorator

System Behaviors go in:
  main.py
  in the WebSocket handler

Utilities go in:
  email_service.py
  database.py
  etc.
```

---

## Your Questions - Quick Answers

**Q: Differentiate MCP & agents?**
- A: MCP = LLM chooses | Agents = System chooses on own

**Q: Is barge-in MCP/agent/other?**
- A: Other - it's a System Behavior (infrastructure)

**Q: Is link dummy?**
- A: No - `https://meet.google.com/new` creates real Google Meet

**Q: How to decide what goes where?**
- A: Use the decision table above
