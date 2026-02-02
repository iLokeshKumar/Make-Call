# Implementation Checklist - Google Meet & Email Collection

## ✅ What's Already Done

- [x] Created `google_calendar_service.py` - handles Google Meet link generation
- [x] Updated `book_meeting()` in `mcp_server.py` - now handles:
  - Email collection if missing
  - Google Meet link generation
  - Auto-update of lead email
  - Enhanced email template with Meet link
  - Proper error handling
- [x] Created `migrate_google_meet.py` - database migration script
- [x] Updated `.env` with Google credentials (you already added them!)

---

## 🔧 Steps to Complete

### Step 1: Download Google Credentials JSON (5 min)

**Location:** Google Cloud Console → APIs & Services → Credentials

**Action:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Find your project or create new one named "Rio Sales Assistant"
3. Enable Google Calendar API
4. Create OAuth2 credentials (Desktop app type)
5. Download JSON file
6. Save as `google_credentials.json` in your project root

**Verify:**
```
c:\Users\User\something_new\outbound-calling-speech-assistant-openai-realtime-api-python\google_credentials.json
```

---

### Step 2: Install Google Calendar Packages (2 min)

```bash
cd c:\Users\User\something_new\outbound-calling-speech-assistant-openai-realtime-api-python

# Install Google libraries
pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dateutil
```

---

### Step 3: Run Database Migration (1 min)

```bash
# From project directory
python migrate_google_meet.py
```

**Expected output:**
```
✅ Successfully added google_meet_link column to appointment table
```

**If column already exists:**
```
✅ google_meet_link column already exists
```

---

### Step 4: Test Google Meet Creation (5 min)

Create a test script to verify Google Meet integration:

**File:** `test_google_meet.py`

```python
#!/usr/bin/env python
"""Quick test of Google Meet integration"""

from google_calendar_service import GoogleMeetGenerator

generator = GoogleMeetGenerator()
print("✅ GoogleMeetGenerator initialized")

# First run will prompt for OAuth authorization
result = generator.create_google_meet_event(
    lead_name="Test Lead",
    lead_email="your-email@gmail.com",
    proposed_time="tomorrow at 3 PM",
    meeting_type="demo",
    duration_minutes=30
)

print("\n" + "="*50)
print("Google Meet Creation Result:")
print("="*50)
print(f"Success: {result.get('success')}")
print(f"Meet Link: {result.get('google_meet_link')}")
print(f"Calendar Link: {result.get('calendar_link')}")
if result.get('error'):
    print(f"Error: {result.get('error')}")
```

**Run test:**
```bash
python test_google_meet.py
```

**First run:** Browser window will open for OAuth (grant permission)
**Result:** Should see Google Meet link printed

---

### Step 5: Verify Email Integration (2 min)

Test that emails now include Meet link:

```python
from mcp_server import book_meeting

# Test with existing email
result = book_meeting(
    lead_id=1,  # Adjust to existing lead
    proposed_time="next Friday at 2 PM",
    meeting_type="demo"
)

print(f"Booking confirmed: {result.get('confirmed')}")
print(f"Meet link: {result.get('google_meet_link')}")
print(f"Email sent: {result.get('email_sent')}")
```

---

### Step 6: Test Email Collection Flow (3 min)

Simulate Rio asking for email:

```python
from mcp_server import book_meeting

# Lead without email - should return needs_email flag
result = book_meeting(
    lead_id=999,  # Use lead without email
    proposed_time="next Monday at 10 AM",
    meeting_type="demo"
)

print(f"Needs email: {result.get('needs_email')}")
print(f"Message: {result.get('message')}")

# If needs_email is True, provide it:
if result.get('needs_email'):
    result = book_meeting(
        lead_id=999,
        proposed_time="next Monday at 10 AM",
        meeting_type="demo",
        lead_email="newuser@example.com"  # Provided by Rio after asking
    )
    
    print(f"After providing email:")
    print(f"Confirmed: {result.get('confirmed')}")
    print(f"Email: {result.get('lead_email')}")
```

---

## 🎯 Key Features Testing

### Feature 1: Email Collection
- [ ] User has no email on file
- [ ] Rio calls `book_meeting()` → returns `needs_email: true`
- [ ] Rio asks user for email
- [ ] Rio calls `book_meeting()` with `lead_email` parameter
- [ ] Booking succeeds and email is sent

### Feature 2: Google Meet Link
- [ ] OAuth token exists or can be obtained
- [ ] Google Calendar API is enabled
- [ ] `create_google_meet_event()` returns valid Meet link
- [ ] Link format: `https://meet.google.com/xxx-yyy-zzz`

### Feature 3: Email with Meet Link
- [ ] Email is sent to lead
- [ ] Email contains:
  - [ ] Meeting type (Demo/Consultation/etc)
  - [ ] Meeting time
  - [ ] Confirmation ID
  - [ ] Google Meet "Join" button
  - [ ] One-click join link

### Feature 4: Database Storage
- [ ] `google_meet_link` column exists in `appointment` table
- [ ] Meet link is stored when appointment is created
- [ ] Can query: `SELECT google_meet_link FROM appointment WHERE id = 123`

---

## 📋 Complete Checklist

```
PRE-SETUP:
  [ ] Google Cloud project created
  [ ] Google Calendar API enabled
  [ ] OAuth credentials created
  [ ] google_credentials.json downloaded to project root
  [ ] Client ID & Secret in .env (already done)

INSTALLATION:
  [ ] Google library packages installed
  [ ] google_calendar_service.py exists in project
  [ ] migrate_google_meet.py executed successfully
  [ ] Database migration completed

TESTING:
  [ ] Google Meet creation tested
  [ ] Email collection flow tested
  [ ] Email with Meet link received
  [ ] Database has google_meet_link column
  [ ] All new fields in book_meeting() response verified

PRODUCTION:
  [ ] google_credentials.json in production environment
  [ ] Google libraries installed in production
  [ ] Database migration run in production
  [ ] .env credentials set correctly in production
  [ ] OAuth token generated in production (first run)
  [ ] Test booking created end-to-end
```

---

## 🔍 Verification Commands

```bash
# Check if google_credentials.json exists
if (Test-Path "google_credentials.json") { Write-Host "✅ Credentials found" } else { Write-Host "❌ Credentials missing" }

# Check if google_calendar_service.py exists
if (Test-Path "google_calendar_service.py") { Write-Host "✅ Service module found" } else { Write-Host "❌ Service module missing" }

# Check if migration script exists
if (Test-Path "migrate_google_meet.py") { Write-Host "✅ Migration script found" } else { Write-Host "❌ Migration script missing" }

# Test Python imports
python -c "from google_calendar_service import GoogleMeetGenerator; print('✅ Imports work')"
```

---

## 🚨 Common Issues & Solutions

| Issue | Solution |
|-------|----------|
| "google_credentials.json not found" | Download from Google Cloud Console, save to project root |
| "Google not installed" | Run `pip install google-auth-oauthlib google-auth-httplib2 google-api-python-client` |
| "Column google_meet_link doesn't exist" | Run `python migrate_google_meet.py` |
| "OAuth requires browser" | Run server on desktop/terminal with browser access |
| "Meet link is None" | Check Google Calendar API is enabled, OAuth token exists |

---

## 📞 What Rio Will Say

### Scenario 1: Email on file
```
User: "I'd like to book a demo"
Rio: "Great! I'll schedule that for you. What time works best?"
User: "Tuesday at 2 PM"
Rio: "Perfect! I've confirmed your demo for Tuesday at 2 PM. 
      A confirmation email with the Google Meet link has been sent 
      to john@example.com. You can join directly from the email. 
      Looking forward to our conversation!"
```

### Scenario 2: No email on file
```
User: "I'd like to book a demo"
Rio: "Absolutely! Before I schedule it, I'll need your email 
      to send the confirmation and video call link. What's your email?"
User: "john@example.com"
Rio: "Great! What time works for your demo?"
User: "Tuesday at 2 PM"
Rio: "Perfect! I've confirmed your demo for Tuesday at 2 PM. 
      A confirmation email with the Google Meet link has been sent 
      to john@example.com. You can join directly from the email. 
      Looking forward to our conversation!"
```

---

## 🎉 Success Indicators

When everything is working:

1. ✅ Database has `google_meet_link` column in `appointment` table
2. ✅ `book_meeting()` returns with `"google_meet_link": "https://meet.google.com/xxx-yyy-zzz"`
3. ✅ Lead receives email with:
   - "Join Google Meet" button
   - One-click meeting link
   - Meeting details
4. ✅ Lead email is automatically saved if not on file
5. ✅ Logs show: "[book_meeting] Google Meet link created: https://meet.google.com/xxx-yyy-zzz"

**Status:** 🚀 READY FOR DEPLOYMENT
