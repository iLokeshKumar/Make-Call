# Rio's Conversation Flows - Email Collection & Booking

## 📋 How Rio Handles Email Collection

Rio now uses a smart flow that naturally asks for email only when needed.

---

## Flow 1: Lead Already Has Email ✅

```
┌─────────────────────────────────────────┐
│ Incoming Call / Message                 │
├─────────────────────────────────────────┤
│                                         │
│ System: Loads lead record               │
│         - Name: John Smith              │
│         - Email: john@acme.com ✅       │
│         - Phone: +1-555-0123            │
│                                         │
│ Rio: "Hi John! Thanks for taking my     │
│      call. How can I help you today?"   │
│                                         │
│ User: "I'd like to schedule a demo"     │
│                                         │
│ Rio: "Absolutely! I'd love to show you  │
│      how our platform can help.         │
│      What time works best for you?"     │
│                                         │
│ User: "Tuesday at 2 PM"                 │
│                                         │
│ Rio: [Calls MCP: book_meeting()]        │
│      - lead_id: 123                     │
│      - proposed_time: "Tuesday 2 PM"    │
│      - meeting_type: "demo"             │
│      (no lead_email param needed)       │
│                                         │
│ System Response: {                      │
│   "confirmed": true,                    │
│   "google_meet_link": "meet.google..",  │
│   "email_sent": true,                   │
│   "needs_email": false                  │
│ }                                       │
│                                         │
│ Rio: "Perfect! I've scheduled your demo │
│      for Tuesday at 2 PM. A             │
│      confirmation with the Google Meet  │
│      link has been sent to              │
│      john@acme.com. You can join        │
│      directly from the email."          │
│                                         │
└─────────────────────────────────────────┘
```

---

## Flow 2: Lead Has NO Email ⚠️

```
┌─────────────────────────────────────────┐
│ Incoming Call / Message                 │
├─────────────────────────────────────────┤
│                                         │
│ System: Loads lead record               │
│         - Name: Jane Doe                │
│         - Email: (empty) ❌             │
│         - Phone: +1-555-9876            │
│                                         │
│ Rio: "Hi Jane! Thanks for taking my     │
│      call. How can I help you today?"   │
│                                         │
│ User: "I want to book a meeting"        │
│                                         │
│ Rio: "Great! I'd be happy to help.      │
│      Before we book, I'll need your     │
│      email to send the confirmation and │
│      meeting link. What's the best      │
│      email address to reach you?"       │
│                                         │
│ User: "jane@example.com"                │
│                                         │
│ Rio: "Perfect! Now, what time works     │
│      best for you?"                     │
│                                         │
│ User: "Next Monday at 10 AM"            │
│                                         │
│ Rio: [Calls MCP: book_meeting()]        │
│      - lead_id: 456                     │
│      - proposed_time: "Monday 10 AM"    │
│      - meeting_type: "demo"             │
│      - lead_email: "jane@example.com"   │
│        (provided by user)               │
│                                         │
│ System Response: {                      │
│   "confirmed": true,                    │
│   "google_meet_link": "meet.google..",  │
│   "email_sent": true,                   │
│   "lead_email": "jane@example.com",     │
│   "needs_email": false                  │
│ }                                       │
│                                         │
│ Rio: "Excellent! I've saved your email  │
│      and scheduled your demo for Monday │
│      at 10 AM. A confirmation with the  │
│      Google Meet link has been sent to  │
│      jane@example.com. You can click    │
│      the link to join when it's time."  │
│                                         │
└─────────────────────────────────────────┘
```

---

## Flow 3: Email Invalid or Declined ⛔

```
┌─────────────────────────────────────────┐
│ Incoming Call / Message                 │
├─────────────────────────────────────────┤
│                                         │
│ Rio: "What's the best email to send     │
│      the confirmation?"                 │
│                                         │
│ User: "I'd rather not share my email"   │
│                                         │
│ Rio: "I completely understand privacy   │
│      concerns. Unfortunately, I can't   │
│      send the meeting link without an   │
│      email. Would you be comfortable    │
│      providing just a different email   │
│      address? Or we could use your      │
│      phone number instead."             │
│                                         │
│ User: "Use my work email: jane.work@... │
│                                         │
│ Rio: "Perfect! [Continue with booking]" │
│                                         │
└─────────────────────────────────────────┘
```

---

## Rio's Smart Email Collection Phrases

### Natural Opening (When Email Needed):

```
📝 Option 1 (Professional):
"Before I schedule that, I'll need your email to send 
the meeting confirmation and video call link. 
What's your email address?"

📝 Option 2 (Casual):
"Just to make sure you get the meeting details and 
link, what email should I send that to?"

📝 Option 3 (Reassuring):
"I'll need your email to send the meeting confirmation 
and Google Meet link. Don't worry, we keep it secure."

📝 Option 4 (If Updated):
"I notice I don't have your email on file anymore. 
Can you share that again so I can send the confirmation?"
```

### Confirmation After Email Provided:

```
✅ Option 1:
"Great! I've saved that and scheduled your [meeting type] 
for [time]. A confirmation email with the Google Meet link 
has been sent to [email]. You can join directly from the 
email when it's time."

✅ Option 2:
"Perfect! Your [meeting type] is confirmed for [time]. 
Check your email at [email] for the confirmation with 
the video call link - just click to join."

✅ Option 3:
"Excellent! I've scheduled you for [time] and sent a 
confirmation to [email]. It includes a one-click Google 
Meet link you can use to join the meeting."
```

### If Email is Invalid:

```
⚠️ Option 1:
"Hmm, that email doesn't look quite right. Can you 
double-check it for me? Just want to make sure you 
get the meeting link."

⚠️ Option 2:
"Let me verify that - could you spell out your email 
address? [Listen] Got it, so that's [repeat]."

⚠️ Option 3:
"I want to make sure I have that right. Your email is 
[repeat email character by character]. Is that correct?"
```

---

## Rio's Booking Confirmation Phrases

### After Successful Booking:

```
🎉 Standard Confirmation:
"Perfect! I've confirmed your [meeting type] for 
[day] at [time]. A confirmation email with your 
Google Meet link has been sent to [email address]. 
You can join directly from the email. Looking forward 
to our conversation!"

🎉 With Lead Name Update:
"Great! I've saved your email ([email]) and scheduled 
your [meeting type] for [day] at [time]. The 
confirmation with the Google Meet link is on its way 
to your inbox. See you then!"

🎉 Enthusiastic:
"Awesome! I've set up your [meeting type] for [day] 
at [time]. Check your email at [address] for the 
confirmation - you'll see the Google Meet link there. 
Just click it when you're ready to join. Thanks!"
```

### What NOT to Say:

```
❌ "I'm saving your email to the database"
❌ "The MCP tool is creating a Google Meet link"
❌ "I'm calling book_meeting with these parameters"
❌ "The confirmation status is: True"
```

Instead, say:

```
✅ "I've saved your email and scheduled the meeting"
✅ "A video call link is being created for you"
✅ "Your meeting is confirmed"
✅ "The confirmation is on its way"
```

---

## Email Collection Edge Cases

### Edge Case 1: User Changes Their Mind About Email

```
Rio: "I'll need your email for the meeting link.
     What's your email?"

User: "Actually, I'd prefer not to give it now."

Rio: "No problem at all! However, you'll need to 
     provide it later to get the meeting confirmation 
     and video link. Would you like to provide it now, 
     or should I note that you'll add it later?"

User: "I'll do it later"

Rio: "Got it. Just remember - without your email, 
     I can't send you the meeting link. When you're 
     ready, just let me know and we'll get it set up."

[Mark appointment as "needs_email_confirmation"]
```

### Edge Case 2: Multiple Email Addresses

```
Rio: "I see you have a phone number on file, but I'll 
     need your email for the meeting link. Do you prefer 
     your personal email or work email?"

User: "Work email: jane@acme.com"

Rio: "Perfect! I've saved jane@acme.com and scheduled 
     your meeting for [time]. The confirmation is being 
     sent there now."
```

### Edge Case 3: User Already Provided Email During Call

```
[Earlier in call, user gave email address]

User: "So let's book that demo"

Rio: "Absolutely! I already have your email 
     ([email from earlier]) - your demo is confirmed 
     for [time] and the confirmation is heading to 
     your inbox right now!"
```

---

## Database/System Updates Triggered

When email is collected and used for booking:

```python
# Automatically executed:
1. ✅ Lead record updated with email
   UPDATE lead SET email = 'jane@example.com' 
   WHERE id = 456

2. ✅ Google Meet link created
   → Call Google Calendar API
   → Return: https://meet.google.com/xxx-yyy-zzz

3. ✅ Appointment created
   INSERT INTO appointment (lead_id, appointment_time, 
   google_meet_link, status) 
   VALUES (456, '2026-02-03 10:00', 'meet.google...', 'scheduled')

4. ✅ Email sent
   TO: jane@example.com
   SUBJECT: Your Demo Meeting is Confirmed
   BODY: [Beautiful HTML with Meet link]

5. ✅ Transcript logged
   INSERT INTO interaction (lead_id, type, content, timestamp)
   VALUES (456, 'call', 'User booked demo for 02/03...', now())
```

---

## Testing Rio's Responses

To test the flow without a real call:

```python
# Test 1: With email
result = book_meeting(lead_id=1, proposed_time="Friday 2 PM")
assert result["confirmed"] == True
assert result["needs_email"] == False
print(f"Rio would say: \"{result['message']}\"")

# Test 2: Without email  
result = book_meeting(lead_id=999, proposed_time="Friday 2 PM")
assert result["needs_email"] == True
print(f"Rio should ask: \"{result['message']}\"")

# Test 3: After email provided
result = book_meeting(
    lead_id=999, 
    proposed_time="Friday 2 PM",
    lead_email="newuser@example.com"
)
assert result["confirmed"] == True
print(f"Rio would say: \"{result['message']}\"")
```

---

## Summary

**Rio's Email Collection is:**
- 🗣️ Conversational (natural language, not robotic)
- 🛡️ Privacy-conscious (explains why email is needed)
- ✨ Seamless (integrated into booking flow)
- 🎯 Efficient (collects email only when needed)
- 💾 Persistent (saves to database for future use)

**Result:** Professional demo booking experience with automatic Google Meet links! 🚀
