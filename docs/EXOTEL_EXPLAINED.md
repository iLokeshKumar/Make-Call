# Exotel API Explained - How It Really Works

## Your Question:
> "From=+918148749703, CallerId=+914448133610 - what is this? It should be calling FROM +914448133610 TO +918148749703!"

## The Answer:

You're thinking like Twilio, but **Exotel works differently**!

---

## Twilio vs Exotel - Key Difference

### Twilio (What you're used to):
```python
# Twilio: Direct call
From: +914448133610  # Your number (source)
To: +918148749703    # Customer (destination)
```
**Meaning:** "Call FROM my number TO customer"

### Exotel (Confusing but correct):
```python
# Exotel: Connect call
From: +918148749703      # Customer (who to call)
CallerId: +914448133610  # Your Exophone (caller ID)
```
**Meaning:** "Call this customer, show my Exophone as caller ID"

---

## Why Is Exotel Different?

Exotel's `/Calls/connect` API is designed for **connecting two parties**, not making a direct call.

Think of it like this:
1. Exotel calls the customer (`From`)
2. When customer answers, they see your Exophone (`CallerId`) on their screen
3. Then Exotel executes your ExoML/Voicebot (`Url`)

It's like a **call bridge**, not a direct dial.

---

## The Real Problem

Looking at your error, the issue isn't the number order - it's the **URL format**:

```
Url: https://my.exotel.com/adomitatechnologies1/exoml/start_voicebot?bot_url=wss%3A%2F%2F...
```

This URL format (`start_voicebot`) might not be correct for your Exotel account.

---

## Solution: Use ExoML Directly

Instead of using `start_voicebot`, we should use ExoML with `<Stream>` tag:

### Old (Not Working):
```python
Url: https://my.exotel.com/.../exoml/start_voicebot?bot_url=wss://...
```

### New (Should Work):
```xml
<!-- ExoML Response -->
<Response>
    <Connect>
        <Stream url="wss://your-domain.com/exotel-media-stream" />
    </Connect>
</Response>
```

Then pass this ExoML as base64:
```python
Url: https://my.exotel.com/.../exoml/start_voice?exoml=<base64_encoded_exoml>
```

---

## Updated Code Explanation

The fix I just applied does this:

```python
# 1. Remove + prefix (Exotel prefers without +)
customer_number = "918148749703"   # Customer to call
exophone_number = "914448133610"   # Your Exophone

# 2. Create ExoML with WebSocket stream
exoml = """
<Response>
    <Connect>
        <Stream url="wss://your-domain.com/exotel-media-stream" />
    </Connect>
</Response>
"""

# 3. Encode ExoML as base64
exoml_b64 = base64.b64encode(exoml.encode()).decode()

# 4. Build Exotel URL
applet_url = f"https://my.exotel.com/{account_sid}/exoml/start_voice?exoml={exoml_b64}"

# 5. Make API call
data = {
    "From": customer_number,      # Who to call
    "CallerId": exophone_number,  # Caller ID to show
    "Url": applet_url,            # ExoML to execute
    "CallType": "trans"
}
```

---

## What Happens When Call Connects

1. **Exotel calls** `918148749703` (customer)
2. **Customer sees** `914448133610` (your Exophone) on their phone
3. **Customer answers**
4. **Exotel executes** the ExoML from `Url`
5. **ExoML connects** to your WebSocket (`wss://...`)
6. **Your Rio bot** starts talking to customer

---

## Common Exotel Errors

### Error 34001: Bad parameters
**Causes:**
- Exophone not verified in Exotel dashboard
- URL not accessible
- Number format incorrect
- Missing required parameters

**Check:**
1. Go to Exotel dashboard → Phone Numbers
2. Verify `914448133610` is active and verified
3. Test if your ngrok URL is accessible
4. Ensure numbers don't have special characters

### Error 34010: Authentication failed
**Causes:**
- Wrong API Key/Token
- Wrong Account SID
- Wrong subdomain (api.exotel.com vs api.in.exotel.com)

**Fix:**
```bash
# Check your credentials
echo $EXOTEL_ACCOUNT_SID  # Should be: adomitatechnologies1
echo $EXOTEL_API_KEY      # Your API key
echo $EXOTEL_API_TOKEN    # Your API token
```

---

## Testing Steps

### 1. Verify Exophone in Dashboard
```
1. Login to https://my.exotel.com
2. Go to "Phone Numbers"
3. Check if 914448133610 is listed and active
4. If not, you need to purchase/verify it first
```

### 2. Test with Simple ExoML
```python
# Test with a simple "Say" instead of Stream
simple_exoml = """<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Say>Hello from Rio CRM</Say>
</Response>"""

exoml_b64 = base64.b64encode(simple_exoml.encode()).decode()
test_url = f"https://my.exotel.com/{account_sid}/exoml/start_voice?exoml={exoml_b64}"

# If this works, the issue is with WebSocket Stream
# If this fails, the issue is with Exophone or credentials
```

### 3. Check Exotel Call Logs
```
1. Go to https://my.exotel.com
2. Navigate to "Call Logs"
3. Look for your test call
4. Check error messages
```

---

## Number Format Guide

Exotel accepts multiple formats, but prefers **without + prefix**:

| Format | Works? | Recommended? |
|--------|--------|--------------|
| `918148749703` | ✅ Yes | ✅ Yes |
| `+918148749703` | ✅ Yes | ⚠️ Sometimes |
| `08148749703` | ❌ No | ❌ No |
| `8148749703` | ❌ No | ❌ No |

**Best practice:** Always use country code without `+`
- India: `91` + 10-digit number
- Example: `918148749703`

---

## Summary

**Your confusion:**
- You thought `From` = your number, `To` = customer
- That's how Twilio works!

**Exotel reality:**
- `From` = customer (who to call)
- `CallerId` = your Exophone (caller ID)
- No `To` parameter exists!

**The fix:**
- Changed URL format from `start_voicebot` to `start_voice` with ExoML
- Removed `+` prefix from numbers
- Added proper ExoML with `<Stream>` tag
- Added better error logging

**Next steps:**
1. Verify your Exophone in Exotel dashboard
2. Test the updated code
3. Check logs for detailed error messages
4. If still failing, try simple ExoML test first

---

**Status:** Updated and explained
**Date:** February 23, 2026
