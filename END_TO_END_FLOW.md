# 🔄 Rio CRM - End-to-End Flow Explanation

This document explains exactly what happens when you use Rio CRM, from clicking "Call" to seeing the transcript.

---

## 📊 Complete System Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    USER INTERFACE (Frontend)                    │
│  http://localhost:3006                                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │Dashboard │  │  Leads   │  │Inventory │  │ Settings │       │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘       │
└───────┼─────────────┼────────────┼────────────┼───────────────┘
        │             │             │             │
        │  HTTP REST API Calls      │             │
        │             │             │             │
        ▼             ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    BACKEND SERVER (FastAPI)                      │
│  http://localhost:6060                                          │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  REST API Endpoints                                      │   │
│  │  • GET  /leads          → Fetch all leads               │   │
│  │  • POST /leads          → Create new lead                │   │
│  │  • POST /make-call      → Initiate outbound call         │   │
│  │  • GET  /interactions   → Get call history              │   │
│  │  • GET  /inventory      → Get products                  │   │
│  │  • PATCH /settings      → Update AI configuration       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  WebSocket Endpoints (Real-time Audio)                  │   │
│  │  • /media-stream        → Twilio audio stream            │   │
│  │  • /enablex-media-stream → EnableX audio stream          │   │
│  └─────────────────────────────────────────────────────────┘   │
└───────┬───────────────────────────────────────────────────────────┘
        │
        │ Database Queries
        │
        ▼
┌─────────────────────────────────────────────────────────────────┐
│                    DATABASE LAYER                               │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐        │
│  │  PostgreSQL/ │  │   ChromaDB   │  │  System      │        │
│  │   SQLite     │  │  (Vector DB) │  │  Settings    │        │
│  │              │  │              │  │              │        │
│  │ • Leads      │  │ • Knowledge  │  │ • AI Script   │        │
│  │ • Calls      │  │   Base       │  │ • Engine     │        │
│  │ • Products    │  │ • Embeddings │  │   Selection  │        │
│  │ • Transcripts │  │              │  │              │        │
│  └──────────────┘  └──────────────┘  └──────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 📞 Complete Call Flow (Step-by-Step)

### Phase 1: Call Initiation

```
User clicks "Call" button in Dashboard
         │
         ▼
Frontend: POST /make-call?to=+1234567890&lead_id=5
         │
         ▼
Backend receives request
         │
         ├─→ Creates Interaction record in database
         │   (id=10, lead_id=5, type="call", timestamp=now)
         │
         ├─→ Checks SystemSettings for active telephony engine
         │   (Twilio or EnableX)
         │
         └─→ Calls Twilio/EnableX API to dial number
```

### Phase 2: Call Connection

```
Twilio/EnableX receives dial request
         │
         ├─→ Dials customer's phone
         │
         └─→ When answered, sends webhook to backend:
             POST /incoming-call (Twilio)
             POST /enablex-event (EnableX)
         │
         ▼
Backend receives webhook
         │
         ├─→ Returns TwiML/EnableX config
         │   (Tells provider to connect WebSocket)
         │
         └─→ Provider connects to:
             wss://your-domain.ngrok-free.app/media-stream
```

### Phase 3: Audio Streaming Setup

```
WebSocket connection established
         │
         ├─→ Backend accepts WebSocket
         │
         ├─→ Loads AI configuration:
         │   • System instructions from database
         │   • Active voice engine (Gemini/Mistral)
         │   • Lead context (if lead_id exists)
         │
         └─→ Initializes voice pipeline
```

### Phase 4: Real-Time Conversation

#### If Using Gemini 2.0 (Native Multimodal):

```
Customer speaks
         │
         ▼
Twilio streams audio (8kHz μ-law)
         │
         ▼
Backend receives audio chunks
         │
         ├─→ Converts: μ-law → PCM 8kHz → PCM 16kHz
         │
         └─→ Sends to Gemini Live API
             (Raw audio, no transcription needed)
         │
         ▼
Gemini processes audio
         │
         ├─→ Understands speech
         │
         ├─→ Generates response (text + audio)
         │
         └─→ May trigger tool calls:
             • check_inventory("Samsung TV")
             • query_knowledge_base("warranty")
             • update_lead_tool(phone, notes, status)
         │
         ▼
Backend receives Gemini response
         │
         ├─→ If tool called:
         │   • Executes Python function
         │   • Queries database
         │   • Returns result to Gemini
         │   • Gemini generates final response
         │
         ├─→ Converts audio: PCM 24kHz → PCM 8kHz → μ-law
         │
         └─→ Sends audio back to Twilio
         │
         ▼
Customer hears AI response
```

#### If Using Mistral Pipeline:

```
Customer speaks
         │
         ▼
Twilio streams audio (8kHz μ-law)
         │
         ▼
Backend receives audio
         │
         └─→ Forwards to Deepgram WebSocket
             (Speech-to-Text)
         │
         ▼
Deepgram transcribes audio → Text
         │
         ▼
Backend receives transcription
         │
         ├─→ Saves to transcript accumulator
         │
         └─→ Sends text to Mistral API
             (with conversation history)
         │
         ▼
Mistral processes text
         │
         ├─→ Generates response text
         │
         └─→ May trigger tool calls (same as Gemini)
         │
         ▼
Backend receives Mistral response
         │
         ├─→ If tool called: Execute and get result
         │
         └─→ Sends text to ElevenLabs
             (Text-to-Speech)
         │
         ▼
ElevenLabs generates audio (PCM 16kHz)
         │
         ▼
Backend converts: PCM 16kHz → PCM 8kHz → μ-law
         │
         └─→ Sends audio back to Twilio
         │
         ▼
Customer hears AI response
```

### Phase 5: Transcript Saving

```
Every conversation turn:
         │
         ├─→ User utterance saved
         │   transcript_accumulator.append("User: Hello")
         │
         ├─→ AI response saved
         │   transcript_accumulator.append("Rio: Hi, how can I help?")
         │
         ├─→ Tool executions saved
         │   transcript_accumulator.append("[System]: Checked inventory...")
         │
         └─→ Incremental save to database
             UPDATE interactions SET transcript = ... WHERE id = 10
```

### Phase 6: Call Completion

```
Customer hangs up OR call ends
         │
         ▼
WebSocket connection closes
         │
         ├─→ Final transcript saved
         │
         ├─→ Interaction record updated
         │   (duration, final status)
         │
         └─→ Lead status updated (if AI called update_lead_tool)
         │
         ▼
User views call in Dashboard
         │
         └─→ GET /interactions → Shows transcript
```

---

## 🔧 Data Flow Examples

### Example 1: Customer Asks About Product

```
1. Customer: "Do you have Samsung 55 TV in stock?"
   │
   ▼
2. Gemini processes → Calls tool: check_inventory("Samsung 55 TV")
   │
   ▼
3. Backend executes:
   SELECT * FROM products WHERE name ILIKE '%Samsung 55 TV%'
   │
   ▼
4. Returns: {"product": "Samsung 55 TV", "stock": 5, "price": "₹65,000"}
   │
   ▼
5. Gemini receives result → Generates response:
   "Yes, we have 5 units in stock at ₹65,000."
   │
   ▼
6. Customer hears response
   │
   ▼
7. Transcript saved:
   User: Do you have Samsung 55 TV in stock?
   [System]: Checked inventory for 'Samsung 55 TV' -> {"stock": 5, ...}
   Rio: Yes, we have 5 units in stock at ₹65,000.
```

### Example 2: Customer Asks About Warranty

```
1. Customer: "What's the warranty on VRF systems?"
   │
   ▼
2. Gemini processes → Calls tool: query_knowledge_base("VRF warranty")
   │
   ▼
3. Backend executes:
   • Embed query using Gemini embeddings
   • Search ChromaDB for similar documents
   • Returns: "The Samsung VRF System usually comes with a 1-year..."
   │
   ▼
4. Gemini receives context → Generates response:
   "The Samsung VRF System comes with a 1-year comprehensive warranty 
    and 5 years on the compressor. AMC options are available."
   │
   ▼
5. Customer hears response
```

### Example 3: AI Updates Lead Status

```
1. Customer: "Yes, I'm interested. Send me a quote."
   │
   ▼
2. Gemini processes → Calls tool: 
   update_lead_tool(phone="+1234567890", notes="Interested in quote", status="Follow-up")
   │
   ▼
3. Backend executes:
   UPDATE leads SET notes = ..., status = 'Follow-up' WHERE phone = '+1234567890'
   │
   ▼
4. Gemini responds: "I'll have our team send you a quote shortly."
   │
   ▼
5. Lead status updated in database
   │
   ▼
6. User sees updated status in Dashboard immediately
```

---

## 🎯 Key Components Interaction

### When You Click "Call" Button:

```
Frontend (React)
    │
    │ HTTP POST /make-call?to=+1234567890&lead_id=5
    │
    ▼
Backend (FastAPI)
    │
    ├─→ Creates Interaction record
    │   (database.py → SQLModel → PostgreSQL/SQLite)
    │
    ├─→ Reads SystemSettings
    │   (database.py → SystemSettings table)
    │
    └─→ Calls Twilio/EnableX API
        (twilio.rest.Client or aiohttp)
    │
    ▼
Twilio/EnableX
    │
    ├─→ Dials phone number
    │
    └─→ Sends webhook when answered
        POST /incoming-call
    │
    ▼
Backend receives webhook
    │
    ├─→ Returns TwiML/EnableX config
    │   (Tells provider to connect WebSocket)
    │
    └─→ Provider connects to WebSocket
        wss://domain/media-stream
    │
    ▼
WebSocket Handler (main.py)
    │
    ├─→ Accepts connection
    │
    ├─→ Loads AI config from database
    │
    ├─→ Loads lead context (if lead_id exists)
    │
    └─→ Routes to voice pipeline:
        • gemini_voice_pipeline() OR
        • mistral_voice_pipeline()
    │
    ▼
AI Engine (Gemini/Mistral)
    │
    ├─→ Processes audio/text
    │
    ├─→ May call tools:
    │   • check_inventory() → Queries Product table
    │   • query_knowledge_base() → Searches ChromaDB
    │   • update_lead_tool() → Updates Lead table
    │
    └─→ Generates response
    │
    ▼
Backend streams response audio
    │
    └─→ Saves transcript incrementally
        (Every turn saved to Interaction.transcript)
    │
    ▼
Customer hears AI response
```

---

## 📦 Data Storage Locations

| Data Type | Storage Location | Access Method |
|-----------|-----------------|---------------|
| **Leads** | PostgreSQL/SQLite (`leads` table) | `GET /leads`, `POST /leads` |
| **Call Transcripts** | PostgreSQL/SQLite (`interactions` table) | `GET /interactions` |
| **Products** | PostgreSQL/SQLite (`products` table) | `GET /inventory` |
| **AI Instructions** | PostgreSQL/SQLite (`system_settings` table) | `GET /settings` |
| **Knowledge Base** | ChromaDB (`knowledge_base/` folder) | Via `query_knowledge_base()` tool |
| **Call Audio** | Not stored (streamed only) | N/A |

---

## 🔄 State Management

### During a Call:

1. **WebSocket Connection** - Maintains real-time audio stream
2. **Transcript Accumulator** - In-memory list of conversation turns
3. **Database Updates** - Incremental saves every turn
4. **AI Context** - Conversation history maintained by AI engine
5. **Tool Results** - Cached during call for efficiency

### After Call Ends:

1. **Final Transcript** - Saved to `interactions.transcript`
2. **Lead Updates** - Any status changes persisted
3. **WebSocket Closed** - Connection terminated
4. **Memory Freed** - Accumulators cleared

---

## 🎛️ Configuration Flow

### When You Change Settings:

```
User edits Settings page
    │
    │ PATCH /settings
    │ {system_instruction: "...", voice_engine: "gemini"}
    │
    ▼
Backend updates SystemSettings table
    │
    ├─→ UPDATE system_settings SET value = ... WHERE key = 'system_instruction'
    │
    └─→ UPDATE system_settings SET value = ... WHERE key = 'voice_engine'
    │
    ▼
Next call uses new settings
    │
    └─→ WebSocket handler reads from database on connection
```

**No server restart needed!** Settings are loaded dynamically.

---

This is the complete end-to-end flow. Every component is connected and working together to create a seamless voice AI experience.


