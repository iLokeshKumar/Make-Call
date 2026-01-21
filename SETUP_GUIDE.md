# 🚀 Rio CRM - Complete Setup & Run Guide

This is a step-by-step guide to get Rio CRM running from scratch.

---

## 📋 Prerequisites

Before starting, ensure you have:

1. **Python 3.12+** installed
   - Check: `python --version` or `python3 --version`
   - Download: https://www.python.org/downloads/

2. **Node.js 18+** installed
   - Check: `node --version`
   - Download: https://nodejs.org/

3. **API Keys** (you'll need these):
   - **Twilio** Account SID, Auth Token, Phone Number
   - **Google Gemini** API Key
   - **EnableX** (optional, for India routing) App ID, App Key
   - **Mistral** API Key (optional, for alternative AI engine)
   - **Deepgram** API Key (optional, for Mistral pipeline)
   - **ElevenLabs** API Key + Voice ID (optional, for Mistral pipeline)
   - **Apollo.io** API Key (optional, for lead enrichment)

4. **Public URL** for webhooks (for production):
   - Use **ngrok** for local testing: https://ngrok.com/
   - Or deploy to a server with public IP

---

## 🔧 Step 1: Clone & Navigate

```bash
# If not already cloned:
git clone https://github.com/iLokeshKumar/Make-Call.git
cd Make-Call
```

---

## 🔐 Step 2: Backend Environment Setup

### 2.1 Navigate to Backend Directory

```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
```

### 2.2 Create `.env` File

Create a file named `.env` in this directory with the following content:

```env
# ============================================
# TELEPHONY CONFIGURATION
# ============================================
# Twilio (Required for basic setup)
TWILIO_ACCOUNT_SID=your_twilio_account_sid_here
TWILIO_AUTH_TOKEN=your_twilio_auth_token_here
PHONE_NUMBER_FROM=+1234567890

# EnableX (Optional - for India routing)
ENABLEX_APP_ID=your_enablex_app_id
ENABLEX_APP_KEY=your_enablex_app_key
ENABLEX_FROM_NUMBER=917550131495

# ============================================
# AI SERVICES
# ============================================
# Gemini (Required - Primary AI Engine)
GEMINI_API_KEY=your_gemini_api_key_here

# Mistral Pipeline (Optional - Alternative AI)
MISTRAL_API_KEY=your_mistral_api_key
DEEPGRAM_API_KEY=your_deepgram_api_key
ELEVENLABS_API_KEY=your_elevenlabs_api_key
ELEVENLABS_VOICE_ID=CwhOLp6mAE7h9asvUURR

# ============================================
# DATA SOURCES
# ============================================
# Apollo.io (Optional - for lead enrichment)
APOLLO_API_KEY=your_apollo_api_key

# ============================================
# INFRASTRUCTURE
# ============================================
# Domain for webhooks (use ngrok for local testing)
# Example: DOMAIN=abc123.ngrok-free.app
DOMAIN=your-domain.ngrok-free.app

# Server Port (default: 6060)
PORT=6060

# Database (Optional - defaults to SQLite)
# For PostgreSQL: DATABASE_URL=postgresql://user:password@localhost:5432/riocrm
# DATABASE_URL=sqlite:///./crm.db
```

### 2.3 Get Your API Keys

**Twilio:**
1. Sign up at https://www.twilio.com/
2. Get Account SID and Auth Token from Dashboard
3. Buy a phone number (or use trial number)

**Google Gemini:**
1. Go to https://aistudio.google.com/
2. Get API key from "Get API Key" section

**EnableX (Optional):**
1. Sign up at https://www.enablex.io/
2. Get App ID and App Key from dashboard

**For Local Testing with ngrok:**
```bash
# Install ngrok: https://ngrok.com/download
# Run:
ngrok http 6060
# Copy the forwarding URL (e.g., https://abc123.ngrok-free.app)
# Use it as DOMAIN in .env (without https://)
```

---

## 🐍 Step 3: Backend Installation

### 3.1 Create Virtual Environment (Recommended)

**Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

**Mac/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3.2 Install Dependencies

```bash
pip install -r requirements.txt
```

This installs:
- FastAPI (web framework)
- Twilio SDK
- Google Gemini SDK
- SQLModel (database ORM)
- ChromaDB (vector database)
- And all other dependencies

### 3.3 Initialize Database

The database will auto-initialize on first run, but you can verify:

```bash
python -c "from database import init_db; init_db()"
```

This creates:
- `crm.db` (SQLite database) with tables: Leads, Interactions, Products, SystemSettings
- `knowledge_base/` (ChromaDB vector store)

---

## ⚛️ Step 4: Frontend Setup

### 4.1 Navigate to Frontend Directory

Open a **new terminal window** (keep backend terminal open):

```bash
cd frontend
```

### 4.2 Install Dependencies

```bash
npm install
```

This installs:
- Next.js 15
- React 19
- Tailwind CSS
- Lucide icons
- And all frontend dependencies

---

## 🚀 Step 5: Running the System

### Option A: One-Click Start (Windows)

Simply run:
```bash
start_servers.bat
```

This opens two command windows:
- Backend on port 6060
- Frontend on port 3006

### Option B: Manual Start

**Terminal 1 - Backend:**
```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
python main.py
```

You should see:
```
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:6060
Database initialized.
```

**Terminal 2 - Frontend:**
```bash
cd frontend
npm run dev
```

You should see:
```
  ▲ Next.js 16.1.1
  - Local:        http://localhost:3006
  - Ready in 2.3s
```

---

## ✅ Step 6: Verify Installation

### 6.1 Check Backend

Open browser: http://localhost:6060

You should see: `"Twilio + Gemini Voice Agent"` and `"Server is running."`

### 6.2 Check Frontend

Open browser: http://localhost:3006

You should see the **Rio CRM Dashboard** with:
- Stats cards (Total Leads, Calls Today, etc.)
- Navigation sidebar
- Modern glass-morphism UI

### 6.3 Test API Endpoints

**Test Leads API:**
```bash
curl http://localhost:6060/leads
```

Should return: `[]` (empty array, which is correct for new install)

**Test Settings API:**
```bash
curl http://localhost:6060/settings
```

Should return JSON with default system instructions.

---

## 📞 Step 7: Making Your First Call

### 7.1 Setup ngrok (For Local Testing)

**Important:** Twilio/EnableX need a public URL to send webhooks. For local testing, use ngrok:

```bash
# Install ngrok from https://ngrok.com/download
# Then run:
ngrok http 6060
```

Copy the forwarding URL (e.g., `https://abc123.ngrok-free.app`)

Update your `.env`:
```env
DOMAIN=abc123.ngrok-free.app
```

Restart the backend server.

### 7.2 Add a Test Lead

1. Go to http://localhost:3006/leads
2. Click "Add Product" or use the upload feature
3. Or manually add via API:

```bash
curl -X POST http://localhost:6060/leads \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Test Customer",
    "phone": "+1234567890",
    "email": "test@example.com",
    "status": "New"
  }'
```

### 7.3 Initiate a Call

**Via Dashboard:**
1. Go to Leads page
2. Find your test lead
3. Click the "Call" button

**Via API:**
```bash
curl -X POST "http://localhost:6060/make-call?to=+1234567890&lead_id=1"
```

### 7.4 What Happens During a Call

1. **Backend receives call request** → Creates Interaction record
2. **Twilio/EnableX dials** → Connects to your server
3. **WebSocket established** → Audio streams in real-time
4. **AI processes conversation** → Gemini/Mistral responds
5. **Transcript saved** → Available in Call History

---

## 🧪 Step 8: Testing Individual Components

### Test Apollo.io Integration

```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
python test_apollo.py
```

### Test Database Connection

```bash
python debug_db.py
```

### Test Knowledge Base (RAG)

The knowledge base is auto-seeded on first run. Test it by:
1. Go to Settings page
2. Modify system instructions to ask about warranty
3. Make a test call and ask: "What's the warranty on VRF systems?"

---

## 🎯 Step 9: Configure AI Behavior

### 9.1 Customize System Instructions

1. Go to http://localhost:3006/settings
2. Edit the "System Instructions / Script" textarea
3. Click "Save Changes"

Example customization:
```
You are Rio, a friendly sales assistant for Yexis Electronics.
Always greet customers warmly.
Keep responses under 2 sentences.
Speak in a professional but approachable tone.
```

### 9.2 Switch AI Engines

In Settings page:
- **Voice Engine**: Toggle between "Gemini 2.0" (faster) and "Mistral Pipeline" (more control)
- **Telephony Engine**: Toggle between "Twilio" (global) and "EnableX" (India optimized)

---

## 📊 Step 10: Add Inventory Products

1. Go to http://localhost:3006/inventory
2. Click "Add Product"
3. Fill in:
   - Product Name: "Samsung 55 TV"
   - Stock: 5
   - Price: "₹65,000"
   - Notes: (optional)
4. Save

Now when customers ask about products during calls, Rio can check inventory!

---

## 🔍 Troubleshooting

### Backend Won't Start

**Error: "Missing environment variables"**
- Check your `.env` file exists
- Verify all required keys are set (at minimum: TWILIO_*, GEMINI_API_KEY, DOMAIN)

**Error: "Port 6060 already in use"**
```bash
# Windows: Find and kill process
netstat -ano | findstr :6060
taskkill /PID <PID> /F

# Mac/Linux:
lsof -ti:6060 | xargs kill
```

### Frontend Won't Start

**Error: "Port 3006 already in use"**
```bash
# Windows:
netstat -ano | findstr :3006
taskkill /PID <PID> /F

# Mac/Linux:
lsof -ti:3006 | xargs kill
```

**Error: "Module not found"**
```bash
cd frontend
rm -rf node_modules package-lock.json
npm install
```

### Calls Not Connecting

1. **Check ngrok is running:**
   ```bash
   ngrok http 6060
   ```

2. **Verify DOMAIN in .env matches ngrok URL** (without https://)

3. **Check Twilio webhook configuration:**
   - In Twilio Console → Phone Numbers → Your Number
   - Voice webhook should be: `https://your-domain.ngrok-free.app/incoming-call`

4. **Check backend logs** for WebSocket connection errors

### AI Not Responding

1. **Verify API keys are valid:**
   - Test Gemini: https://aistudio.google.com/
   - Check API quota/limits

2. **Check backend console** for error messages

3. **Verify audio format** - Twilio sends μ-law 8kHz, which is auto-converted

---

## 📝 Quick Reference

### Important URLs

- **Frontend Dashboard**: http://localhost:3006
- **Backend API**: http://localhost:6060
- **API Docs**: http://localhost:6060/docs (FastAPI auto-generated)

### Key Directories

- **Backend Code**: `outbound-calling-speech-assistant-openai-realtime-api-python/`
- **Frontend Code**: `frontend/src/`
- **Database**: `outbound-calling-speech-assistant-openai-realtime-api-python/crm.db`
- **Knowledge Base**: `outbound-calling-speech-assistant-openai-realtime-api-python/knowledge_base/`

### Environment File Location

- **Backend .env**: `outbound-calling-speech-assistant-openai-realtime-api-python/.env`

---

## 🎉 You're Ready!

Your Rio CRM system is now running. You can:

✅ Manage leads from the dashboard  
✅ Make AI-powered voice calls  
✅ Track call history and transcripts  
✅ Manage inventory  
✅ Configure AI behavior  
✅ Import leads from Apollo.io  

**Next Steps:**
- Add real leads
- Customize AI instructions for your business
- Set up production deployment
- Configure email sequences (future feature)

---

## 🆘 Need Help?

- Check backend console for errors
- Check frontend browser console (F12)
- Review logs in terminal windows
- Verify all API keys are valid
- Ensure ngrok is running for local webhook testing

