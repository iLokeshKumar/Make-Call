# 🧪 Voice Agent Labs

This directory contains standalone, high-performance "Labs" to test the latest all-in-one Voice Agent APIs. These scripts are isolated from the main CRM to provide the fastest testing environment possible.

## 📁 Available Labs

### 1. Deepgram + Gemini Agent (`/labs/deepgram_agent/`)
- **What it is**: Uses Deepgram's native Voice Agent API (STT + LLM + TTS in one WebSocket).
- **Core Stack**: 
  - **STT**: `flux-general-en` (Advanced conversational model)
  - **LLM**: `gemini-1.5-flash` (Integrated via Deepgram)
  - **TTS**: `aura-2-odysseus-en` (Aura v2 Voice)
- **Status**: Ready to test 🚀

## 🛠️ Setup Instructions

### 1. Prerequisites
- **ngrok**: Required to expose your local server to Twilio.
- **Python**: Ensure you have the dependencies from the main project.

### 2. Running a Lab
Each lab is a standalone script.
1. Open a terminal.
2. Start the lab:
   ```bash
   python labs/deepgram_agent/phone_lab.py
   ```
3. The lab runs on port **8082**.

### 3. Exposing to the Phone
1. In a separate terminal, start ngrok:
   ```bash
   ngrok http 8082
   ```
2. Copy the "Forwarding" URL (e.g., `https://abc-123.ngrok-free.app`).
3. Log in to your **Twilio Console**.
4. Go to your Phone Number settings.
5. Set the **A CALL COMES IN** webhook to:
   `https://your-ngrok-url.ngrok-free.app/voice`
6. Save and **Call your number**!

## 🧪 Testing Focus
- **Latency**: Notice how fast the response starts (Time to First Word).
- **Conciseness**: The instructions are set to "Ultra-Concise" to test 1-word or 1-sentence speed.
- **Interruptions**: Try talking over the AI to see how gracefully it handles flow.
