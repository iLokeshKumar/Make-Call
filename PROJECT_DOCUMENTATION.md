# Project Documentation: Rio CRM & AI Voice Assistant

## 1. Core Idea & Vision
**Project Name:** Rio CRM (AI Voice Assistant for Yexis Electronics)

**The Problem:**
Traditional CRM systems are static data repositories. Sales teams spend hours manually logging data, and customers often face long wait times or impersonal IVR (Interactive Voice Response) menus when calling for support or inquiries.

**The Solution:**
**Rio** is an intelligent, agentic CRM that bridges the gap between data and communication. It is not just a dashboard but an **active AI employee** capable of:
*   Holding natural, ultra-low latency voice conversations with customers.
*   Understanding complex queries about products (Samsung B2B catalog), warranties, and policies using RAG (Retrieval Augmented Generation).
*   Automatically updating the CRM database with lead details, call notes, and statuses.
*   Speaking multiple languages (English, Hindi, Tamil, etc.) to serve a diverse customer base in India.

---

## 2. Technology Stack & Rationale ("What & Why")

We chose a modern, high-performance stack designed for real-time capabilities and scalability.

### A. The Brain: Google Gemini 2.0 Flash (Multimodal Live API)
*   **What it is:** Google's latest multimodal model capable of processing text and audio natively.
*   **Why we chose it:**
    *   **Native Audio:** Unlike older pipelines (Speech-to-Text -> LLM -> Text-to-Speech) which are slow, Gemini 2.0 accepts and generates audio directly. This results in **sub-second latency**, crucial for natural voice conversations.
    *   **Multimodality:** It understands tone, nuance, and interruptions better than text-only models.
    *   **Cost & Speed:** The "Flash" variant is optimized for high-throughput, low-latency tasks.

### B. The Ear & Mouth: Twilio Media Streams
*   **What it is:** A programmable telephony platform that handles the actual phone lines (PSTN).
*   **Why we chose it:**
    *   **WebSocket Support:** Twilio `Media Streams` allows us to stream raw audio to our server in real-time, rather than recording and uploading files. This is essential for live conversation.
    *   **Global Reach:** Provides reliable phone numbers and carrier connections worldwide.

### C. The Backend: Python & FastAPI
*   **What it is:** A modern, fast (high-performance) web framework for building APIs with Python.
*   **Why we chose it:**
    *   **Async/Await:** FastAPI is built on Starlette and supports asynchronous programming out of the box. This is critical for handling **WebSockets** (for audio streaming) where blocking operations would kill the call quality.
    *   **Python Ecosystem:** Python is the native language of AI. Using Python allows us to integrate Gemini, ChromaDB, and other AI libraries seamlessly without context switching.

### D. The Frontend: Next.js 15 (React) & Tailwind CSS
*   **What it is:** A React framework for production-grade web applications.
*   **Why we chose it:**
    *   **Server-Side Rendering (SSR):** Next.js is fast and SEO-friendly.
    *   **Developer Experience:** The "App Router" and TypeScript integration provide a robust structure for building complex dashboards (Leads, Calls, Settings).
    *   **Tailwind CSS:** Allows us to build a premium, "SaaS-style" UI (like the one we built with the Zinc/Slate theme) rapidly without writing custom CSS files.

### E. The Memory (Data Layer): PostgreSQL & ChromaDB
*   **PostgreSQL (Primary DB):**
    *   **Why:** We need structured, reliable storage for business-critical data like Leads, Phone Numbers, and Call Logs. PostgreSQL is the industry standard for relational data.
    *   **SQLModel:** We used SQLModel (by the creator of FastAPI) to interact with the DB using Python classes, reducing code and errors.
*   **ChromaDB (Vector Store):**
    *   **Why:** To implement **RAG (Retrieval Augmented Generation)**. Standard databases can't easily answer "What is the warranty policy?". ChromaDB stores "embeddings" (mathematical representations of text) allowing the AI to search for *concepts* rather than just keywords.

---

## 3. Key Features Implemented

### 🗣️ Conversational AI Agent ("Rio")
*   **Behavior:** Professional, warm, helpful sales assistant.
*   **Capabilities:** Check inventory, answer policy questions, update user status.
*   **Tool Use:** The AI can "call" Python functions (e.g., `check_inventory("Samsung TV")`) to get real-time data during the conversation.

### 📚 Knowledge Base (RAG)
*   We seeded a knowledge base with Yexis Electronics' specific data (Return Policy, Warranty Info, Support Hours).
*   When a user asks a question, the system searches this database and feeds the relevant info to the AI, ensuring accurate answers.

### 📊 Agentic CRM Dashboard
*   **Lead Management:** Add, view, and manage potential clients.
*   **One-Click Call:** A "Call" button on the dashboard triggers the AI to dial the customer immediately, passing the customer's name and history to the AI so the conversation is personalized from the first second.

---

## 4. Architecture Diagram (Conceptual)

```
[Customer Phone] <== PSTN ==> [Twilio] <== WebSocket (Audio) ==> [FastAPI Backend] <==> [Google Gemini AI]
                                    ^                                   ^
                                    |                                   | (Tools)
                                [frontend]                        [Database Layer]
                            (Next.js Dashboard)                 (Postgres + ChromaDB)
```

---

## 5. Vision 2.0: AI Inside Sales Platform

We are evolving from a "Voice Bot" to a "Unified Sales Intelligence Engine."

### 🚀 Sales Orchestration
*   **Quotation Systems**: Rio will be able to check real-time pricing and confirm quotes via tool-calling during live calls.
*   **Warm Handoffs**: If a deal requires complex human handling, Rio will "bridge" the call to an **Inside Sales Rep (ISR)** seamlessly.
*   **Multi-Model Bridge**: Native support for **Qwen2.5-Omni**, **OpenAI**, and **Mistral** to ensure zero-downtime and best-in-class conversation quality.

### 🔍 Prospecting & Data "Waterfall"
*   **Apollo.ai Integration**: Automated data enrichment to find leads, emails, and phone numbers.
*   **Waterfall Discovery**: A system that multi-searches external databases to validate and discovery premium contact data (NumberNexus).
*   **Omnichannel Outreach**: Integrated email sequences that automatically follow up after a call.

**The Result:** A 10x faster sales cycle, guaranteed lead follow-up, and a unified experience for both the customer and the sales rep.
