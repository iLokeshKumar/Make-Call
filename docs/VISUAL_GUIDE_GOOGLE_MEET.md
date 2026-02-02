# Visual Guide: Email Collection & Google Meet Integration

## System Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Rio AI Sales Assistant                    │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐                                           │
│   │   User/Lead     │                                           │
│   │  (Call/Message) │                                           │
│   └────────┬────────┘                                           │
│            │                                                     │
│   ┌────────▼─────────────────────────────────────────┐         │
│   │  Rio: "When would you like to schedule a demo?" │         │
│   └────────┬─────────────────────────────────────────┘         │
│            │                                                     │
│   ┌────────▼────────────────────────────────────────┐          │
│   │  Mistral LLM                                    │          │
│   │  ├─ Understands user intent: "book demo"       │          │
│   │  ├─ Extracts: time = "Tuesday 2 PM"            │          │
│   │  ├─ Calls MCP Tool: book_meeting(...)          │          │
│   │  └─ lead_id: 123, proposed_time: "Tue 2 PM"   │          │
│   └────────┬────────────────────────────────────────┘          │
│            │                                                     │
│   ┌────────▼───────────────────────────────────────────────┐  │
│   │  book_meeting() MCP Tool in mcp_server.py              │  │
│   │  ├─ Check if lead has email ────────────┐             │  │
│   │  │   ├─ YES → Continue to step 2         │             │  │
│   │  │   └─ NO → Return needs_email: true    │             │  │
│   │  │      (Rio asks user for email)        │             │  │
│   │  │      (Rio calls book_meeting again    │             │  │
│   │  │       with lead_email parameter)      │             │  │
│   │  │                                       │             │  │
│   │  ├─ [Step 2] Google Meet Link Generation│             │  │
│   │  │   ├─ Call google_calendar_service.py │             │  │
│   │  │   ├─ Connect to Google Calendar API  │             │  │
│   │  │   ├─ Create event with video conf.   │             │  │
│   │  │   └─ Get Meet link: meet.google.../..│             │  │
│   │  │                                       │             │  │
│   │  ├─ [Step 3] Create DB Appointment      │             │  │
│   │  │   ├─ INSERT INTO appointment         │             │  │
│   │  │   ├─ Store: lead_id, time, status    │             │  │
│   │  │   ├─ Store: google_meet_link         │             │  │
│   │  │   └─ Return: appointment_id          │             │  │
│   │  │                                       │             │  │
│   │  ├─ [Step 4] Send Confirmation Email    │             │  │
│   │  │   ├─ Call email_service.py           │             │  │
│   │  │   ├─ TO: lead_email                  │             │  │
│   │  │   ├─ Include: Meet link              │             │  │
│   │  │   ├─ Include: Join button            │             │  │
│   │  │   └─ Set email_sent: true            │             │  │
│   │  │                                       │             │  │
│   │  └─ [Step 5] Return Success             │             │  │
│   │      confirmed: true                     │             │  │
│   │      google_meet_link: "meet.google..   │             │  │
│   │      email_sent: true                    │             │  │
│   │      appointment_id: 789                 │             │  │
│   └────────┬───────────────────────────────────────────────┘  │
│            │                                                     │
│   ┌────────▼──────────────────────────────┐                   │
│   │  Mistral: "Perfect! I've scheduled    │                   │
│   │           your demo for Tuesday 2 PM. │                   │
│   │           Check your email for the     │                   │
│   │           Google Meet link."           │                   │
│   └────────┬──────────────────────────────┘                   │
│            │                                                     │
│            └──► User: Receives email with Meet link ◄──────┐   │
│                                                            │   │
│                                                    ┌───────▼── │
│                                                    │ Lead's   │ │
│                                                    │ Inbox   │ │
│                                                    └─────────  │
│                                                               │
└──────────────────────────────────────────────────────────────┘
```

---

## Email Collection Decision Tree

```
                    book_meeting() called
                           │
                    ┌──────▼──────┐
                    │ Lead has    │
                    │ email?      │
                    └──────┬──────┘
                           │
                ┌──────────┼──────────┐
                │                    │
              YES                   NO
                │                    │
                │          ┌─────────▼────────┐
                │          │ lead_email param │
                │          │ provided?        │
                │          └─────────┬────────┘
                │                    │
                │            ┌───────┼────────┐
                │            │               │
                │          YES              NO
                │            │               │
                │    ┌─────────▼────────┐   │
                │    │ Update lead      │   │
                │    │ email in DB      │   │
                │    └─────────┬────────┘   │
                │              │            │
                │              ▼            │
                ├─────► Proceed to ◄────────┤
                │     Meet generation       │
                │                           │
                │            ┌──────────────▼──────────┐
                │            │ Return:               │
                │            │ needs_email: true     │
                │            │ message: "Please...   │
                │            │ provide email"        │
                │            └───────────────────────┘
                │                   │
                │                   └──► Rio asks user
                │                        User provides email
                │                        Rio calls book_meeting()
                │                        again with lead_email
                │                        (loop back to top)
                │
                ▼
            Proceed to step 2
            (Create Meet link)
```

---

## Email Template Visual

```
┌────────────────────────────────────────────────────────────┐
│                                                            │
│  ╔════════════════════════════════════════════════════╗   │
│  ║  Demo Confirmed!                                  ║   │
│  ╚════════════════════════════════════════════════════╝   │
│                                                            │
│  Hi John,                                                  │
│                                                            │
│  Great news! Your demo has been scheduled successfully.    │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ 📅 Meeting Details:                                 │ │
│  │ • Type: Demo                                        │ │
│  │ • Time: Tuesday at 2:00 PM                          │ │
│  │ • Confirmation ID: #456                             │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ 📞 Join on Google Meet                              │ │
│  │                                                      │ │
│  │   ┌──────────────────────────────────────────┐      │ │
│  │   │  [🎥 JOIN GOOGLE MEET]                   │      │ │
│  │   └──────────────────────────────────────────┘      │ │
│  │                                                      │ │
│  │ This is an automated Google Meet link.              │ │
│  │ You can join directly from this email.              │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                            │
│  [View Full Meeting Details Button]                       │
│                                                            │
│  If you need to reschedule or have any questions,         │
│  please reply to this email.                              │
│                                                            │
│  Looking forward to our conversation!                     │
│                                                            │
│  ───────────────────────────────────────────────────────  │
│  Rio - Your AI Sales Assistant                            │
│  Powered by Advanced Conversational AI                    │
│                                                            │
└────────────────────────────────────────────────────────────┘
```

---

## Data Flow: Before & After

### BEFORE (Without Google Meet)

```
User books demo
  ↓
Create appointment in DB
  ↓
Send basic email
  ↓
User has to manually create Meet link elsewhere
  ↓
❌ No Meet link in confirmation
❌ Lead has to find separate video call
❌ Friction in user experience
```

### AFTER (With Google Meet Integration)

```
User books demo
  ↓
Collect email if missing
  ↓
Auto-generate Google Meet link
  ↓
Create appointment + store Meet link in DB
  ↓
Send beautiful email with Meet link
  ↓
✅ User clicks email → sees Meet link immediately
✅ User clicks Meet link → joins video call
✅ Seamless, professional experience
```

---

## Response Sequence

```
Step 1: Mistral calls book_meeting()
───────────────────────────────────────
Input:
{
  "lead_id": 123,
  "proposed_time": "Tuesday 2 PM",
  "meeting_type": "demo"
}


Step 2: Check email on file
───────────────────────────────────────
Lead record:
{
  "id": 123,
  "name": "John Smith",
  "email": "john@acme.com"  ✅ FOUND
}


Step 3: Generate Google Meet link
───────────────────────────────────────
Google Calendar API:
  Create Event
    Title: Demo with John Smith
    Time: Tuesday 2026-01-28 14:00
    Attendee: john@acme.com
    Conference: Google Meet
    ↓
  Result: https://meet.google.com/abc-def-ghi


Step 4: Create appointment in DB
───────────────────────────────────────
INSERT INTO appointment
  lead_id: 123
  appointment_time: 2026-01-28 14:00
  google_meet_link: https://meet.google.com/abc-def-ghi
  status: scheduled
  ↓
  RETURNING id: 456


Step 5: Send email
───────────────────────────────────────
FROM: sales@rio.ai
TO: john@acme.com
SUBJECT: Your Demo Meeting is Confirmed
BODY: [HTML email with Meet link button]


Step 6: Return success
───────────────────────────────────────
{
  "confirmed": true,
  "appointment_id": 456,
  "lead_name": "John Smith",
  "lead_email": "john@acme.com",
  "google_meet_link": "https://meet.google.com/abc-def-ghi",
  "email_sent": true,
  "needs_email": false,
  "message": "✅ Demo confirmed for John Smith on Tuesday at 2 PM"
}


Step 7: Mistral confirms to user
───────────────────────────────────────
Rio: "Perfect! I've scheduled your demo for 
     Tuesday at 2 PM. A confirmation with the 
     Google Meet link has been sent to 
     john@acme.com. You can join directly 
     from the email. See you then!"
```

---

## Storage & Retrieval

```
┌─ APPOINTMENT TABLE
│
├─ id (Primary Key): 456
├─ lead_id: 123 (Foreign Key to lead table)
├─ appointment_time: 2026-01-28 14:00:00
├─ status: "scheduled"
├─ google_meet_link: "https://meet.google.com/abc-def-ghi"  ← NEW!
├─ created_at: 2026-01-27 10:30:00
└─ updated_at: 2026-01-27 10:30:00


┌─ LEAD TABLE
│
├─ id: 123
├─ name: "John Smith"
├─ phone: "+1-555-0123"
├─ email: "john@acme.com"  ← SAVED if collected
├─ status: "qualified"
└─ ...

┌─ INTERACTION TABLE
│
├─ id: 789
├─ lead_id: 123
├─ type: "booking"
├─ content: "[call] User booked demo for 2026-01-28 14:00"
└─ timestamp: 2026-01-27 10:30:00
```

---

## Integration Points

```
main.py
  ├─ Mistral LLM (calls book_meeting tool)
  │
  ├─ tool_adapter.py (routes to book_meeting)
  │
  └─ mcp_server.py
      ├─ book_meeting() function
      ├─  calls: google_calendar_service.py
      │         └─ create_google_meet_for_booking()
      ├─  calls: email_service.py
      │         └─ send_smtp_email()
      └─  calls: database
              ├─ SELECT lead WHERE id = ?
              ├─ UPDATE lead SET email = ?
              ├─ INSERT INTO appointment (with google_meet_link)
              └─ SELECT/INSERT to interaction
```

---

## Success Flow Diagram

```
START: User says "book a demo"
│
├─ ✅ Email on file
│  │
│  ├─ ✅ Generate Meet link
│  │
│  ├─ ✅ Create appointment
│  │
│  ├─ ✅ Send email
│  │
│  └─ ✅ Return success
│
└─ END: Rio confirms booking, user receives email with Meet link
    └─ User gets: [✉️ Demo Confirmed] 
                   [Meet Link: https://meet.google.com/...]
                   [Join Button: Click to join]
```

---

## Error Flow Diagrams

```
ERROR 1: No Email on File
─────────────────────────
book_meeting(lead_id=123, time="Tue 2PM", lead_email=None)
  │
  └─ Lead has no email
     └─ Return: {needs_email: true, message: "Ask for email"}
        └─ Rio asks user for email
           └─ User provides: "jane@example.com"
              └─ book_meeting(..., lead_email="jane@example.com")
                 └─ ✅ Continue normal flow


ERROR 2: Google Calendar API Down
──────────────────────────────────
book_meeting(...) 
  │
  └─ Generate Meet link
     └─ Google API unreachable
        └─ Log warning, continue
           └─ Create appointment WITHOUT Meet link
              └─ Send email WITHOUT Meet link
                 └─ Return: {
                     confirmed: true,
                     google_meet_link: None,
                     message: "Demo booked but Meet link unavailable"
                   }
                 └─ ⚠️ Rio: "Demo confirmed but Meet link couldn't be generated"


ERROR 3: Email Service Down
──────────────────────────
book_meeting(...)
  │
  └─ Create appointment ✅
     └─ Send email
        └─ SMTP unreachable
           └─ Log warning, continue
              └─ Return: {
                  confirmed: true,
                  email_sent: false,
                  message: "Booked but email not sent"
                }
              └─ ⚠️ Rio: "Demo is confirmed but confirmation email failed"
```

---

This comprehensive visual guide shows exactly how the system works end-to-end! 🚀
