# Rio CRM - AI Voice & Sales Assistant

**Rio** is a next-generation AI Sales Assistant designed for **Yexis Electronics**. It combines a real-time voice agent with a full-stack CRM dashboard to automate customer interactions, manage leads, and answer complex queries using RAG (Retrieval-Augmented Generation).

![Rio Dashboard](https://github.com/user-attachments/assets/placeholder)

## 🚀 Features

### 🤖 AI Voice Agent
-   **Real-time Conversations**: \<1s latency voice interaction using **Google Gemini 2.0 Flash** + **Twilio Media Streams**.
-   **Contextual Awareness**: Knows exactly who is calling (Name, History, Status) and updates the CRM automatically.
-   **Multilingual**: Speaks English, Hindi, Tamil, Telugu, Malayalam, Urdu, and Sanskrit.
-   **Tool Use**:
    -   `check_inventory`: Checks live stock and pricing.
    -   `query_knowledge_base`: Answers policy/warranty questions using **RAG** (ChromaDB).
    -   `update_lead`: Saves call notes and status directly to the database.

### 💻 Modern CRM Dashboard
-   **Tech Stack**: Next.js 15, React, Tailwind CSS.
-   **Theme**: Professional Light Mode (SaaS/Enterprise style).
-   **Capabilities**:
    -   manage Leads (Add/Edit/Search).
    -   **One-Click Call**: Trigger AI calls directly from the browser.
    -   View Call History & Settings.

### ⚙️ Backend Architecture
-   **FastAPI**: High-performance Python web server.
-   **PostgreSQL**: Primary database for Leads and Call logs.
-   **ChromaDB**: Vector store for RAG (Knowledge Base).
-   **WebSockets**: Bi-directional audio streaming for voice.

---

## 🛠️ Installation & Setup

### Prerequisites
-   Python 3.12+
-   Node.js 18+
-   Twilio Account (SID, Token, Phone Number)
-   Google Gemini API Key

### 1. clone the Repository
```bash
git clone https://github.com/iLokeshKumar/Make-Call.git
cd Make-Call
```

### 2. Backend Setup
Navigate to the backend folder and install dependencies:
```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
pip install -r requirements.txt
```

Create a `.env` file in this folder:
```env
TWILIO_ACCOUNT_SID=your_sid
TWILIO_AUTH_TOKEN=your_token
PHONE_NUMBER_FROM=+1234567890
GEMINI_API_KEY=your_gemini_key
DATABASE_URL=postgresql://user:pass@localhost/calls
DOMAIN=your-ngrok-url.ngrok-free.app
PORT=6060
```

### 3. Frontend Setup
Navigate to the frontend folder and install dependencies:
```bash
cd ../frontend
npm install
```

---

## 🚀 Usage

### One-Click Start (Windows)
Simply run the startup script:
```bash
start_servers.bat
```
This will launch both the Backend (Port 6060) and Frontend (Port 3006).

### Manual Start
**Backend:**
```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
python main.py
```

**Frontend:**
```bash
cd frontend
npm run dev
```

### Access the App
Open your browser and go to:
[http://localhost:3006](http://localhost:3006)

---

## 🤝 Contribution
Feel free to open issues or submit PRs.

## 📄 License
MIT License.
