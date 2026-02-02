# Google Meet Integration & Enhanced Booking Setup Guide

## Overview

Your booking system now supports:
1. ✅ **Automatic email collection** - Rio asks for email if not on file
2. ✅ **Dynamic Google Meet link generation** - Creates video call link for every demo
3. ✅ **Email confirmation with Meet link** - Sends beautiful confirmation email with one-click Join button
4. ✅ **Lead email auto-update** - Saves collected email to lead record

---

## Part 1: Setup Google Calendar API

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a Project" → "New Project"
3. Name it: `Rio Sales Assistant`
4. Click "Create"

### Step 2: Enable Google Calendar API

1. In the Google Cloud Console, go to **APIs & Services** → **Library**
2. Search for **"Google Calendar API"**
3. Click on it and press **"Enable"**

### Step 3: Create OAuth2 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **"+ Create Credentials"** → **"OAuth client ID"**
3. You may be asked to configure the OAuth consent screen first:
   - Click **"Configure OAuth Consent Screen"**
   - Choose **"External"** user type
   - Fill in:
     - **App name**: Rio Sales Assistant
     - **User support email**: your-email@gmail.com
     - **Developer contact**: your-email@gmail.com
   - Click "Save and Continue" → "Save and Continue" → "Back to Dashboard"

4. Now create the OAuth2 credential again:
   - Click **"+ Create Credentials"** → **"OAuth client ID"**
   - Application type: **"Desktop app"**
   - Name: `Rio - Local Dev`
   - Click "Create"

5. You'll see the credentials. Click **"Download"** (JSON file)

### Step 4: Add Credentials to Your Project

1. Place the downloaded JSON file in your project root as `google_credentials.json`

2. Update `.env` with your Client ID and Secret (already in your .env):
```dotenv
Client_ID=YOUR_CLIENT_ID
Client_Secret=YOUR_CLIENT_SECRET
```

---

## Part 2: Setup Your Database

The appointment table now needs a column to store the Google Meet link.

### Run the Migration:

```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
python migrate_google_meet.py
```

**Output should be:**
```
✅ Successfully added google_meet_link column to appointment table
```

---

## Part 3: Install Required Python Packages

```bash
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dateutil
```

---

## Part 4: How It Works

### Flow Diagram:

```
┌─────────────────────────────────────────────────────────────────┐
│                     Booking Flow with Google Meet               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  User: "I'd like to book a demo"                                │
│    ↓                                                             │
│  Rio calls: book_meeting(lead_id=123, time="Tuesday 2PM")       │
│    ↓                                                             │
│  1️⃣  Fetch lead from database                                  │
│    ├─ Has email? → Continue to step 2                          │
│    └─ No email? → Return "needs_email: true"                   │
│        ↓                                                         │
│        Rio: "I need your email to send confirmation"            │
│        User: "john@example.com"                                 │
│        Rio calls: book_meeting(..., lead_email="john@...")      │
│    ↓                                                             │
│  2️⃣  Create Google Meet link                                   │
│    ├─ Call Google Calendar API                                 │
│    ├─ Create event with video conference (Google Meet)         │
│    └─ Return Meet link: https://meet.google.com/abc-def-ghi    │
│    ↓                                                             │
│  3️⃣  Create appointment in database                            │
│    ├─ Store appointment_id                                     │
│    ├─ Store google_meet_link                                   │
│    └─ Set status = "scheduled"                                 │
│    ↓                                                             │
│  4️⃣  Send confirmation email                                   │
│    ├─ Subject: "Your Demo Meeting is Confirmed"                │
│    ├─ Body: Beautiful HTML with:                               │
│    │   • Meeting details                                       │
│    │   • Google Meet join button                               │
│    │   • Confirmation ID                                       │
│    └─ Send to lead_email                                       │
│    ↓                                                             │
│  5️⃣  Return success                                            │
│    ├─ confirmed: true                                          │
│    ├─ appointment_id: 456                                      │
│    ├─ google_meet_link: "https://meet.google.com/abc-def-ghi"  │
│    ├─ email_sent: true                                         │
│    └─ message: "✅ Demo confirmed for John on Tuesday 2PM"     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Part 5: Testing

### Test 1: Booking with existing email

```python
result = book_meeting(
    lead_id=1,
    proposed_time="Friday at 3 PM",
    meeting_type="demo"
)

# Expected output:
# {
#     "confirmed": True,
#     "google_meet_link": "https://meet.google.com/xxx-yyy-zzz",
#     "email_sent": True,
#     "needs_email": False,
#     "message": "✅ Demo confirmed for John Smith on Friday at 3 PM | Meet: https://meet.google... | Invite sent to john@example.com"
# }
```

### Test 2: Booking without email (Rio will ask)

```python
result = book_meeting(
    lead_id=2,  # Lead with no email on file
    proposed_time="Monday at 10 AM",
    meeting_type="demo"
)

# Expected output:
# {
#     "confirmed": False,
#     "needs_email": True,
#     "lead_name": "Jane Doe",
#     "message": "⚠️ Jane Doe doesn't have an email on file. Please ask them for their email address so we can send the meeting confirmation."
# }

# Then Rio asks user for email...
# User provides: jane@example.com

# Rio calls again with email:
result = book_meeting(
    lead_id=2,
    proposed_time="Monday at 10 AM",
    meeting_type="demo",
    lead_email="jane@example.com"
)

# Now it succeeds:
# {
#     "confirmed": True,
#     "google_meet_link": "https://meet.google.com/xxx-yyy-zzz",
#     "email_sent": True,
#     "message": "✅ Demo confirmed for Jane Doe on Monday at 10 AM | Meet: https://meet.google... | Invite sent to jane@example.com"
# }
```

---

## Part 6: What Gets Sent in the Email

The confirmation email now includes:

```html
┌─────────────────────────────────────┐
│   Demo Confirmed!                   │
├─────────────────────────────────────┤
│                                     │
│   Hi John,                          │
│                                     │
│   Great news! Your demo has been    │
│   scheduled successfully.           │
│                                     │
│   ┌─ Meeting Details ─────────────┐ │
│   │ Type: Demo                    │ │
│   │ Time: Tuesday at 2:00 PM      │ │
│   │ Confirmation ID: #456         │ │
│   └───────────────────────────────┘ │
│                                     │
│   ┌─ Join on Google Meet ────────┐ │
│   │   [JOIN GOOGLE MEET]          │ │
│   │   (One-click join link)       │ │
│   └───────────────────────────────┘ │
│                                     │
│   [View Full Details Button]        │
│                                     │
│   If you need to reschedule...     │
│                                     │
│   Rio - Your AI Sales Assistant    │
│                                     │
└─────────────────────────────────────┘
```

---

## Part 7: First Time Setup - OAuth Authorization

When Rio first creates a Google Meet link, Google will:

1. Open a browser window asking for permission
2. You'll see: "Rio Sales Assistant wants to access your Google Calendar"
3. Click "Allow"
4. A token will be saved locally (`token.pickle`)
5. Future bookings will use the cached token (no manual approval needed)

**Pro Tip:** Run this on the machine where your server runs, or the OAuth flow won't work.

---

## Part 8: Environment Variables Checklist

Verify your `.env` has:

```dotenv
# ✅ Existing email settings
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=YOUR_EMAIL
SMTP_PASSWORD=YOUR_APP_PASSWORD
SENDER_EMAIL=YOUR_EMAIL

# ✅ Google OAuth credentials
Client_ID=YOUR_CLIENT_ID
Client_Secret=YOUR_CLIENT_SECRET

# ✅ Database
DATABASE_URL=postgresql://postgres:1234@localhost/calls
```

---

## Part 9: Troubleshooting

### Issue: "Google Calendar not authenticated"

**Solution:**
```bash
# Delete the old token and reauthenticate
rm token.pickle

# Restart your server - it will prompt for OAuth authorization
python main.py
```

### Issue: "Google credentials not available"

**Solution:**
1. Download `google_credentials.json` from Google Cloud Console
2. Place it in project root
3. Restart server

### Issue: "Could not parse meeting time"

**Solution:** Use clearer time formats:
- ✅ "Tuesday at 2 PM"
- ✅ "2026-01-30 14:00"
- ✅ "tomorrow at 10 AM"
- ✅ "next Friday 3:30 PM"

### Issue: Email not sending

**Solution:** Check Gmail app password:
1. Go to [Gmail Account Security](https://myaccount.google.com/security)
2. Generate a new app password
3. Update `SMTP_PASSWORD` in `.env`

---

## Part 10: What Rio Will Say

When booking without email on file:

**Rio:** "I'm ready to schedule your demo! Just so I can send you the meeting confirmation and Google Meet link, what's your email address?"

After getting email and booking:

**Rio:** "Perfect! I've scheduled your demo for Tuesday at 2 PM. A confirmation email with the Google Meet link has been sent to john@example.com. You can join directly from the email when it's time. Looking forward to our conversation!"

---

## Part 11: Key Features Implemented

| Feature | Before | After |
|---------|--------|-------|
| Email collection | ❌ Not handled | ✅ Rio asks if missing |
| Email storage | ❌ Never saved | ✅ Auto-updates lead record |
| Google Meet link | ❌ None | ✅ Generated automatically |
| Confirmation email | ✅ Basic | ✅ With Meet link & button |
| Database support | ❌ No Meet column | ✅ Stores Meet link |

---

## Summary

Your booking system is now **enterprise-grade**:

- 🎥 Every demo has a Google Meet link
- 📧 Email is collected automatically if missing
- 💾 Email is stored for future reference
- 📨 Beautiful confirmation emails sent instantly
- 🔗 One-click join from email
- 📊 All data logged in database
- ✨ Rio guides the entire flow conversationally

**You're ready to deploy!** 🚀
