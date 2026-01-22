# Rio CRM - AI Voice & Sales Assistant

**Rio** is a next-generation AI Sales Assistant designed for **Yexis Electronics** and **Talentrus**. It combines a real-time voice agent with a full-stack CRM dashboard to automate customer interactions, manage leads, and answer complex queries using RAG (Retrieval-Augmented Generation).

---

## 🚀 Latest Updates

### 🎙️ Multi-Engine Voice AI
- **Dual Architecture**: Switch seamlessly between **Gemini 2.0 Flash** (native multimodal) and a custom **Mistral/Deepgram/ElevenLabs** pipeline.
- **Low Latency**: Real-time WebSocket streaming ensures response times under 500ms.

### 📞 Telephony Abstraction
- **EnableX Integration**: Full support for EnableX telephony alongside Twilio, providing local routing and cost-effective scaling for the Indian market.
- **Dynamic Routing**: Toggle between carriers instantly via the Settings dashboard.

### 📥 Intelligent Lead Ingestion
- **Apollo.io Integration**: Automated lead fetching from Apollo's organization database.
- **Bulk Upload**: Standardized processing for Excel and CSV files with duplicate detection.
- **Audit Trails**: Every record now tracks `created_by`, `updated_by`, and timestamps for full transparency.

### � Dynamic Management
- **Inventory Control**: Add and edit products live. Rio's brain updates instantly to reflect current stock and pricing.
- **Live Scripting**: Modify Rio's personality and instructions from the dashboard without restarting the server.

---

## 🎯 Long-Term Vision: The Autonomous Sales Operation

Our goal is to transform Rio from a simple assistant into a fully **Autonomous Sales Operation** capable of handling the entire top-of-funnel lifecycle:

- **Phase 1: Prospecting & Enrichment**: Full "Waterfall" enrichment (Local -> Apollo -> Lusha -> Validation) to ensure high-quality contact data.
- **Phase 2: Multi-Channel Sequence**: Automated follow-ups via Voice, WhatsApp, and Email based on customer sentiment.
- **Phase 3: Live Handoff**: Intelligent escalation to human sales reps for high-value leads with real-time context transfer.
- **Phase 4: Quote to Close**: Automated PDF quotation generation and CRM conversion using deep tool-calling integrations.

---

## 🛠️ Installation & Setup

### Prerequisites
-   Python 3.12+
-   Node.js 18+
-   API Keys for: Twilio/EnableX, Gemini, Deepgram, ElevenLabs, Mistral, Apollo.io.

### 1. Clone the Repository
```bash
git clone https://github.com/iLokeshKumar/Make-Call.git
cd Make-Call
```

### 2. Backend Setup
```bash
cd outbound-calling-speech-assistant-openai-realtime-api-python
pip install -r requirements.txt
```

### 3. Frontend Setup
```bash
cd ../frontend
npm install
```

---

## 🚀 Usage

### One-Click Start (Windows)
Run `start_servers.bat` to launch both the Backend (6060) and Frontend (3006).

---

## 🤝 Partners & Attribution
**Developed by [Adomita](https://adomita.com/)** for:
- [Yexis Solutions](https://www.yexis.in/)
- [Yexis Electronics](https://www.yexiselectronics.com/)
- [Talentrus](https://talentrus.net/)
- [Talentrus Manufacturing](https://manufacturing.talentrus.net/)
- [Talentrus Distribution](https://distribution.talentrus.net/)

## 🔒 License
Proprietary and Confidential. Unauthorized use or distribution is prohibited.
