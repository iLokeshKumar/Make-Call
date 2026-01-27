# Rio CRM - Complete Architecture Diagram

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    RIO CRM SALES PLATFORM                       │
│                   (Persona-First AI Agent)                      │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐
│  VOICE GATEWAY   │          Rio = Senior Sales Consultant
│  (Twilio/EnableX)│          Not a bot. Has persona, goals, guardrails.
└─────────┬────────┘
          │
          ↓
    ┌─────────────┐
    │ AUDIO STREAM│
    └─────────────┘
          │
          ↓
┌─────────────────────────────────────────────────────────────────┐
│         PHASE 2: RIO PERSONA + SYSTEM PROMPT                    │
│                     (main.py)                                   │
├─────────────────────────────────────────────────────────────────┤
│  Role: Senior Sales Consultant                                  │
│  Task: BANT Qualification (Budget, Authority, Need, Timeline)  │
│  Guardrails: No price hallucination, max 10% discount          │
│  Action: Book demo if qualified, nurture otherwise             │
└─────────────────────────────────────────────────────────────────┘
          │
          ↓
┌─────────────────────────────────────────────────────────────────┐
│       PHASE 1: MCP TOOLS (Deterministic - No Hallucination)     │
│                  (mcp_server.py)                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Tool 1: check_icp_qualification()                          │ │
│  │ → Is lead Enterprise/Mid/SMB? Right industry?              │ │
│  │ → Output: {is_qualified, priority}                         │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Tool 2: get_product_info()                                 │ │
│  │ → Get ACTUAL prices from database (no hallucination!)      │ │
│  │ → Output: {name, price, stock, min_authorized_price}      │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Tool 3: check_guardrails()                                 │ │
│  │ → Discount allowed? (Max 10% auto-approved)                │ │
│  │ → Output: {approved, requires_manager}                     │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Tool 4: book_meeting()                                     │ │
│  │ → Schedule demo in database/calendar                       │ │
│  │ → Output: {appointment_id, calendar_url}                   │ │
│  └────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
          │
          ↓
┌─────────────────────────────────────────────────────────────────┐
│   PHASE 3: HYBRID TOOL LAYER (80% Deterministic / 20% Agentic)  │
│                   (tools/ directory)                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  DETERMINISTIC (80%) ✓ No Errors                               │
│  ├── tools/booking.py                                           │
│  │   ├── book_meeting() → Create appointment in DB             │
│  │   └── cancel_meeting() → Cancel appointment                 │
│  │                                                              │
│  ├── tools/discount.py                                          │
│  │   ├── validate_discount() → Check guardrails                │
│  │   └── apply_discount() → Calculate final price              │
│  │                                                              │
│  ├── tools/email.py                                             │
│  │   ├── send_followup_email() → Send templated emails         │
│  │   ├── send_personalized_email() → Send custom emails        │
│  │   └── Templates: default, demo-booked, not-qualified, etc.  │
│  │                                                              │
│  AGENTIC (20%) ⚡ Flexible                                      │
│  └── tools/query.py                                             │
│      ├── check_lead_status() → Get lead history                │
│      ├── semantic_query() → "Show NY leads" → AI writes SQL     │
│      └── search_leads_by_criteria() → Multi-field search        │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
          │
          ↓
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 4: LANGGRAPH ORCHESTRATOR (Multi-Agent Workflow)          │
│           (agents/langgraph_orchestrator.py)                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────┐      ┌──────────┐     ┌──────────┐              │
│  │RESEARCHER│      │  VOICE   │     │SUMMARIZER│              │
│  │  AGENT   │──→   │  AGENT   │──→  │  AGENT   │              │
│  │(Prep)    │      │(Call)    │     │(Analyze) │              │
│  └──────────┘      └──────────┘     └──────────┘              │
│                                           │                    │
│                                           ↓                    │
│                                    ┌────────────┐              │
│                                    │ DECISION   │              │
│                                    │  ROUTER    │              │
│                                    └────────────┘              │
│                                    /           \               │
│                          ICP > 0.75            ICP ≤ 0.75     │
│                          & Positive            or Neutral     │
│                            /                      \            │
│                           ↓                        ↓           │
│                    ┌────────────┐          ┌────────────┐    │
│                    │  BOOKING   │          │  NURTURE   │    │
│                    │   AGENT    │          │   AGENT    │    │
│                    │(Schedule   │          │(Send       │    │
│                    │ Demo)      │          │ Email)     │    │
│                    └────────────┘          └────────────┘    │
│                           │                      │            │
│                           └──────────┬───────────┘            │
│                                      ↓                        │
│                                   END ✓                       │
│                                                                │
└─────────────────────────────────────────────────────────────────┘
          │
          ↓
┌─────────────────────────────────────────────────────────────────┐
│  PHASE 5: POST-CALL NURTURE (3 Autonomous Agents)               │
│           (agents/post_call_nurture.py)                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────┐                                            │
│  │ CALL SUMMARIZER │                                            │
│  │   AGENT         │                                            │
│  ├─────────────────┤                                            │
│  │ Analyzes:       │                                            │
│  │ • Sentiment     │                                            │
│  │ • Pain points   │                                            │
│  │ • Questions     │                                            │
│  │ • Objections    │                                            │
│  │ • Buying signals│                                            │
│  │                 │                                            │
│  │ Outputs:        │                                            │
│  │ {icp_score,    │                                            │
│  │  sentiment,    │                                            │
│  │  pain_points,  │                                            │
│  │  bant_answers} │                                            │
│  └────────┬────────┘                                            │
│           ↓                                                     │
│  ┌─────────────────┐                                            │
│  │ CRM UPDATER     │                                            │
│  │  AGENT          │                                            │
│  ├─────────────────┤                                            │
│  │ Actions:        │                                            │
│  │ • Update lead   │                                            │
│  │   status in DB  │                                            │
│  │ • Log           │                                            │
│  │   interaction   │                                            │
│  │ • Save call     │                                            │
│  │   summary as    │                                            │
│  │   JSON          │                                            │
│  └────────┬────────┘                                            │
│           ↓                                                     │
│  ┌─────────────────────────────────┐                            │
│  │ EMAIL WRITER AGENT              │                            │
│  ├─────────────────────────────────┤                            │
│  │ Generates personalized email:    │                            │
│  │                                  │                            │
│  │ Subject: "John, your Rio demo    │                            │
│  │           is ready"               │                            │
│  │                                  │                            │
│  │ Body: References pain points     │                            │
│  │       + questions from call      │                            │
│  │       + personalized next steps  │                            │
│  │                                  │                            │
│  │ Templates:                       │                            │
│  │ • demo-booked (for qualified)    │                            │
│  │ • discount-offer (price asked)   │                            │
│  │ • not-qualified (resources)      │                            │
│  │                                  │                            │
│  │ Sends: Via SMTP email service    │                            │
│  └─────────────────────────────────┘                            │
│           ↓                                                     │
│       Lead Updated ✓                                            │
│       Status changed                                            │
│       Email sent                                                │
│       CRM enriched                                              │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📊 Data Flow During Call

```
┌─────────────────────────────────────────────────────────────────┐
│                      DURING VOICE CALL                          │
└─────────────────────────────────────────────────────────────────┘

Lead Calls
    ↓
Rio Answers (Gemini 2.0 Flash)
    ↓
Rio: "Hi, I'm Rio. What challenges are you facing?"
Lead: "We need better lead management"
    ↓
Rio queries MCP tools:
    │
    ├→ check_icp_qualification("Enterprise", "Tech", 1000)
    │  ← {"is_qualified": true, "priority": "high"}
    │
    ├→ (Continue BANT conversation)
    │
    ├→ Lead asks: "How much is it?"
    │  └→ get_product_info("Rio CRM Platform")
    │     ← {"price": 50000, "stock": 10}
    │
    ├→ Rio: "Our platform starts at $50k/year"
    │
    ├→ Lead: "Can you do 15% off?"
    │  └→ check_guardrails(15.0)
    │     ← {"approved": false, "requires_manager": true}
    │
    ├→ Rio: "That requires manager approval, but I can start the 
    │      process. Let's book a demo first."
    │
    ├→ Lead: "OK, Thursday 2pm works"
    │  └→ book_meeting(lead_id=123, proposed_time="2026-01-30T14:00:00")
    │     ← {"appointment_id": 456, "confirmed": true}
    │
    └→ Rio: "Perfect! Demo confirmed for Thursday 2pm. 
          Confirmation email coming to your inbox."

    ↓
Call ends
    ↓

┌─────────────────────────────────────────────────────────────────┐
│                      AFTER CALL (Async)                         │
└─────────────────────────────────────────────────────────────────┘

        ↓
    [SUMMARIZER]
        ├→ Extract: icp_score=0.85, sentiment="positive"
        ├→ Extract: pain_points=["Lead management"]
        ├→ Extract: questions=["Pricing", "Discount"]
        └→ Save JSON summary to DB
        ↓
    [CRM UPDATER]
        ├→ Update lead.status = "Demo Scheduled"
        ├→ Log interaction: "Call completed, demo booked"
        └→ Save call summary to interactions table
        ↓
    [EMAIL WRITER]
        ├→ Generate personalized email:
        │  Subject: "John, your Rio CRM demo is Thursday 2pm"
        │  Body: "We discussed lead management challenges...
        │         Here's the demo link..."
        └→ Send email
        ↓
    Lead Updated ✓
    Status: "Demo Scheduled"
    CRM enriched
    Confirmation email sent
```

---

## 🔄 Flow Routing Decision

```
After Voice Call:

Summarizer extracts ICP score & sentiment
        ↓
    ┌───────────────────────────┐
    │ DECISION LOGIC            │
    ├───────────────────────────┤
    │ If icp_score > 0.75 AND   │
    │    call_outcome = positive│ ──→ [BOOKING AGENT]
    │    Then: Book demo            └→ Schedule & confirm
    │                                 Send demo email
    │                                 Update status
    │
    │ Elif icp_score ≤ 0.75 OR  │
    │      call_outcome = neutral───→ [NURTURE AGENT]
    │      Then: Send nurture        └→ Choose template
    │                                   Send follow-up email
    │                                   Schedule next touch
    │
    │ Else: Not qualified ──────────→ [NURTURE AGENT]
    │       Send resources email      └→ "not-qualified"
    │                                   template
    └───────────────────────────┘
```

---

## 💾 Database Integration

```
┌──────────────────────────────────┐
│         DATABASE TABLES          │
├──────────────────────────────────┤
│                                  │
│  leads/                          │
│  ├── id, name, email, phone      │
│  ├── status ← UPDATED BY AGENTS  │
│  ├── source                      │
│  └── enrichment_status           │
│                                  │
│  interactions/                   │
│  ├── id, lead_id, type           │
│  ├── content ← CALL SUMMARY JSON │
│  └── timestamp                   │
│                                  │
│  appointments/                   │
│  ├── id, lead_id, status         │
│  ├── appointment_time ← booked   │
│  └── type ("demo", "consultation")
│                                  │
│  system_settings/                │
│  ├── key = "system_instruction"  │
│  └── value = RIO_PERSONA_PROMPT  │
│                                  │
│  products/                       │
│  ├── name, price, stock          │
│  └── note (lead_time, etc)       │
│                                  │
└──────────────────────────────────┘
```

---

## 🔐 Guardrails Flow

```
┌──────────────────────────────────────────────┐
│         GUARDRAILS ENFORCEMENT               │
├──────────────────────────────────────────────┤
│                                              │
│  Guardrail 1: ICP Check                     │
│  ├→ Before offering anything                │
│  ├→ Tool: check_icp_qualification()         │
│  └→ Block if not qualified                  │
│                                              │
│  Guardrail 2: Pricing Accuracy               │
│  ├→ Never hallucinate prices                │
│  ├→ Tool: get_product_info()                │
│  ├→ Fetch from DB always                    │
│  └→ If not in DB: Say "I'll check"          │
│                                              │
│  Guardrail 3: Discount Limits                │
│  ├→ Max 10% auto-approved                   │
│  ├→ >10% requires manager review            │
│  ├→ Tool: check_guardrails()                │
│  └→ Tell user: "Needs approval"             │
│                                              │
│  Guardrail 4: Demo Booking Consent          │
│  ├→ Never assume consent                    │
│  ├→ Say: "Shall I schedule that?"           │
│  ├→ Wait for explicit "yes"                 │
│  ├→ Tool: book_meeting()                    │
│  └→ Only call if confirmed                  │
│                                              │
└──────────────────────────────────────────────┘
```

---

## 📈 Success Path

```
Lead Calls
    ↓
Rio Qualifies (BANT)
    ├→ Budget? ✓
    ├→ Authority? ✓
    ├→ Need? ✓
    └→ Timeline? ✓
    ↓
ICP Score = 0.85 (Qualified)
    ↓
[BOOKING AGENT]
    ├→ book_meeting() ✓
    ├→ Update status → "Demo Scheduled" ✓
    └→ Send confirmation email ✓
    ↓
Lead has demo scheduled
Demo email in inbox
CRM shows "Demo Scheduled"
    ↓
→ Follow-up sequence begins
```

---

## 📞 Rio's Decision Logic

```
DURING CALL:
"How much does it cost?"
    ↓
    Rio calls get_product_info()
    ↓
    Rio responds with EXACT price from DB
    ✓ No hallucination

"Can you do 20% off?"
    ↓
    Rio calls check_guardrails(20)
    ↓
    Result: requires_manager = true
    ↓
    Rio: "That's above my auto-approval limit. 
          Let me get manager to review. 
          But first, let's book the demo?"
    ✓ Guardrails enforced

"Alright, Thursday 2pm?"
    ↓
    Rio calls book_meeting(lead_id, time)
    ↓
    Result: confirmed = true, appointment_id = 456
    ↓
    Rio: "Perfect! Demo scheduled. 
          Confirmation email on the way."
    ✓ Action taken

AFTER CALL:
    [SUMMARIZER] → "Positive, ICP 0.85"
    [CRM UPDATER] → "Status: Demo Scheduled"
    [EMAIL WRITER] → Send confirmation
    ✓ Fully automated
```

---

**Architecture Complete & Documented**  
**Status**: ✅ Production Ready  
**Date**: January 24, 2026
