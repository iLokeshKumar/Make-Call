# ⚡ Rio CRM - Quick Start Checklist

Follow these steps in order to get Rio running in 10 minutes.

---

## ✅ Pre-Flight Checklist

- [ ] Python 3.12+ installed (`python --version`)
- [ ] Node.js 18+ installed (`node --version`)
- [ ] API Keys ready (Twilio, Gemini minimum)
- [ ] ngrok installed (for local webhook testing)

---

## 🚀 Quick Start (5 Steps)

### Step 1: Backend Setup (2 minutes)

```bash
# Navigate to backend
cd outbound-calling-speech-assistant-openai-realtime-api-python

# Create .env file (copy template below)
# Install dependencies
pip install -r requirements.txt
```

**.env Template (Minimum Required):**
```env
TWILIO_ACCOUNT_SID=your_twilio_sid
TWILIO_AUTH_TOKEN=your_twilio_token
PHONE_NUMBER_FROM=+1234567890
GEMINI_API_KEY=your_gemini_key
DOMAIN=your-ngrok-url.ngrok-free.app
PORT=6060
```

### Step 2: Frontend Setup (1 minute)

```bash
# Open NEW terminal
cd frontend
npm install
```

### Step 3: Start ngrok (1 minute)

```bash
# Open NEW terminal
ngrok http 6060
# Copy the URL (e.g., https://abc123.ngrok-free.app)
# Update DOMAIN in .env file (use: abc123.ngrok-free.app)
```

### Step 4: Start Servers (1 minute)

**Option A - Windows:**
```bash
start_servers.bat
```

**Option B - Manual:**
```bash
# Terminal 1 - Backend
cd outbound-calling-speech-assistant-openai-realtime-api-python
python main.py

# Terminal 2 - Frontend  
cd frontend
npm run dev
```

### Step 5: Verify (30 seconds)

- [ ] Backend: http://localhost:6060 shows "Server is running"
- [ ] Frontend: http://localhost:3006 shows dashboard
- [ ] No errors in terminal windows

---

## 🎯 First Test Call

1. **Add a test lead:**
   - Go to http://localhost:3006/leads
   - Add manually or upload CSV

2. **Make a call:**
   - Click "Call" button next to lead
   - Or use API: `POST /make-call?to=+1234567890`

3. **Check results:**
   - Go to http://localhost:3006/calls
   - View transcript

---

## 🔧 Common Issues

| Issue | Solution |
|-------|----------|
| Port 6060 in use | Kill process or change PORT in .env |
| Port 3006 in use | Kill process or change port in package.json |
| "Missing env vars" | Check .env file exists and has all keys |
| Calls not connecting | Verify ngrok is running and DOMAIN matches |
| AI not responding | Check Gemini API key is valid |

---

## 📞 Need Help?

See `SETUP_GUIDE.md` for detailed explanations.


