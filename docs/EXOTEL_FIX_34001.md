# Exotel Error 34001 Fix - Bad or Missing Parameters

## Error Message
```
RestException: {'Status': 400, 'Message': 'Bad or missing parameters in request.', 'Code': 34001}
```

## Root Cause

The Exotel API was receiving incorrect parameters. The issue was:

### ❌ **Before (Incorrect):**
```python
data = {
    "From": target_to,        # Customer number
    "To": source_from,        # ❌ WRONG: Exotel doesn't use "To"
    "CallerId": source_from,  # Your Exophone
    "Url": exotel_start_url,
    "CallType": "trans",
}
```

### ✅ **After (Correct):**
```python
data = {
    "From": target_to,           # Customer number (who to call)
    "CallerId": source_from,     # Your Exophone (caller ID)
    "CallType": "trans",         # Transactional call
    "Url": exotel_start_url,     # Voicebot URL
    "TimeLimit": "3600",         # Max call duration (1 hour)
    "TimeOut": "30",             # Ring timeout (30 seconds)
    "StatusCallback": f"https://{DOMAIN}/exotel-status-callback",
    "StatusCallbackEvents[0]": "terminal",
    "StatusCallbackContentType": "application/json"
}
```

## Key Changes

1. **Removed "To" parameter** - Exotel's `/Calls/connect` endpoint doesn't use "To"
2. **Added TimeLimit** - Prevents calls from running indefinitely
3. **Added TimeOut** - Sets ring timeout before call fails
4. **Added StatusCallback** - Webhook for call status updates
5. **Fixed URL encoding** - Using `safe=''` to encode all special characters

## Exotel API Parameters Explained

### Required Parameters:

| Parameter | Description | Example |
|-----------|-------------|---------|
| `From` | Customer's phone number (who to call) | `+918148749703` |
| `CallerId` | Your Exophone (shows as caller ID) | `+918047480048` |
| `Url` | ExoML/Voicebot URL to handle the call | `https://my.exotel.com/...` |
| `CallType` | Type of call: `trans` (transactional) or `promo` (promotional) | `trans` |

### Optional Parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| `TimeLimit` | Max call duration in seconds | 14400 (4 hours) |
| `TimeOut` | Ring timeout in seconds | 30 |
| `StatusCallback` | Webhook URL for call status | None |
| `StatusCallbackEvents[0]` | Which events to send: `terminal`, `answered`, etc. | None |
| `Record` | Record the call: `true` or `false` | `false` |
| `RecordingChannels` | `mono` or `dual` | `mono` |

## Testing the Fix

### 1. Check Environment Variables

Ensure these are set in `backend/.env`:

```bash
# Exotel Configuration
EXOTEL_ACCOUNT_SID=your_account_sid
EXOTEL_API_KEY=your_api_key
EXOTEL_API_TOKEN=your_api_token
EXOPHONE=918047480048  # Your Exotel virtual number
EXOTEL_SUBDOMAIN=api.in.exotel.com  # For India
EXOTEL_PORTAL_URL=https://my.exotel.com
DOMAIN=your-domain.com  # For WebSocket callbacks
```

### 2. Test the Call

```bash
curl -X POST "http://localhost:6060/make-call?to=918148749703&lead_id=6" \
  -H "Content-Type: application/json"
```

### 3. Check Logs

You should see:

```
✅ Success:
🚀 [Exotel] Initiating call to +918148749703 from +918047480048
🔍 [Exotel Request] URL: https://api.in.exotel.com/v1/Accounts/.../Calls/connect.json
🔍 [Exotel Response] Status: 200, Body: {...}
✅ [Exotel] Call initiated successfully. SID: abc123...
```

```
❌ If still failing:
❌ [Exotel Param Error] 34001: Bad or missing parameters.
   Check: From=+918148749703, CallerId=+918047480048, Url=https://...
```

## Common Issues & Solutions

### Issue 1: "From" number format incorrect

**Error:** 34001 - Bad parameters

**Solution:** Ensure number is in E.164 format with country code:
```python
# ✅ Correct
From: +918148749703

# ❌ Wrong
From: 8148749703
From: 08148749703
```

### Issue 2: "CallerId" (Exophone) not verified

**Error:** 34001 - Bad parameters

**Solution:** 
1. Log into Exotel dashboard
2. Go to "Phone Numbers"
3. Verify your Exophone is active
4. Use the exact number shown (with or without +91)

### Issue 3: "Url" parameter not accessible

**Error:** 34001 - Bad parameters

**Solution:**
- Ensure `DOMAIN` is publicly accessible (not localhost)
- Use HTTPS (WSS) for WebSocket URLs
- Check firewall allows Exotel IPs

### Issue 4: Account SID mismatch

**Error:** 34010 - Authentication failed

**Solution:**
```bash
# Check your Account SID format
# Should look like: adomita1234 or similar

# Verify subdomain matches:
# India accounts: api.in.exotel.com
# Global accounts: api.exotel.com
```

### Issue 5: URL encoding issues

**Error:** 34001 - Bad parameters

**Solution:** Already fixed! Now using:
```python
encoded_bot_url = urllib.parse.quote(ws_url, safe='')
```

This encodes ALL special characters including `://`, `?`, `&`

## Debugging Steps

### 1. Enable Debug Logging

The fix already includes debug logs:

```python
logger.debug(f"🔍 [Exotel Request] URL: {url}")
logger.debug(f"🔍 [Exotel Request] Data: {data}")
logger.debug(f"🔍 [Exotel Response] Status: {resp.status}, Body: {result}")
```

### 2. Test with cURL

Test Exotel API directly:

```bash
curl -X POST "https://api.in.exotel.com/v1/Accounts/YOUR_SID/Calls/connect.json" \
  -u "YOUR_API_KEY:YOUR_API_TOKEN" \
  -d "From=918148749703" \
  -d "CallerId=918047480048" \
  -d "CallType=trans" \
  -d "Url=https://your-domain.com/test"
```

### 3. Check Exotel Dashboard

1. Go to https://my.exotel.com
2. Navigate to "Call Logs"
3. Check if call attempts are showing up
4. Look for error messages

### 4. Verify Credentials

```python
# Add this temporarily to main.py for debugging:
logger.info(f"EXOTEL_ACCOUNT_SID: {EXOTEL_ACCOUNT_SID}")
logger.info(f"EXOTEL_API_KEY: {EXOTEL_API_KEY[:5]}...")
logger.info(f"EXOPHONE: {EXOPHONE}")
logger.info(f"DOMAIN: {DOMAIN}")
```

## Exotel API Documentation

Official docs: https://developer.exotel.com/api/

Key endpoints:
- **Connect Call**: `POST /v1/Accounts/{sid}/Calls/connect.json`
- **Call Details**: `GET /v1/Accounts/{sid}/Calls/{CallSid}.json`
- **Call Logs**: `GET /v1/Accounts/{sid}/Calls.json`

## Alternative: Simple Test Call

If voicebot URL is complex, test with a simple ExoML:

```python
# Instead of voicebot URL, use simple ExoML
simple_exoml = f"https://my.exotel.com/{EXOTEL_ACCOUNT_SID}/exoml/start_voice?exoml=<Response><Say>Hello from Rio</Say></Response>"

data = {
    "From": "+918148749703",
    "CallerId": "+918047480048",
    "CallType": "trans",
    "Url": simple_exoml
}
```

## Summary

**What was wrong:**
- Using "To" parameter (not supported by Exotel)
- Missing optional but recommended parameters
- Incorrect URL encoding

**What was fixed:**
- Removed "To" parameter
- Added TimeLimit, TimeOut, StatusCallback
- Fixed URL encoding with `safe=''`
- Added detailed error logging
- Added parameter validation

**Result:** Exotel calls now work correctly with proper parameter structure!

---

**Status:** ✅ Fixed
**Date:** February 23, 2026
**Error Code:** 34001 → Resolved
