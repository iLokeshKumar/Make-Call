# Telephony Integration Requirements: MyVelox (Velox Cloud)

To integrate MyVelox as a telephony provider for your AI Voice Assistant, the following technical details and credentials are required. This document can be shared with your MyVelox representative or used as a checklist in their developer portal.

## 1. API Authentication & Credentials
For our backend to initiate calls and manage communications, we need:
*   **Account / Project ID**: The unique identifier for your Velox organization.
*   **API Key / Auth Token**: A secure token for authenticating REST API requests.
*   **API Base URL**: The endpoint for Velox's Programmable Voice API.

## 2. Programmable Voice Capabilities
The provider must support these core features:
*   **Outbound Call Triggering**: An API endpoint to programmatically start a call and point it to a specific logic (Webhook/WebSocket).
*   **Inbound Call Webhooks**: A configuration setting to send a POST request to our server when a call is received on a Velox number.
*   **Status Callbacks**: Real-time HTTP notifications for call states (e.g., `ringing`, `answered`, `completed`).

## 3. Real-Time Media Streaming (Critical)
To enable low-latency AI conversations (like your current Twilio setup), we require **WebSocket-based Media Streaming**.
*   **Requirement**: Does Velox support streaming raw PCM or Mu-Law audio via a bi-directional WebSocket during a call?
*   **Twilio Equivalent**: This is equivalent to Twilio's `<Stream>` TwiML instruction.
*   **Alternative (SIP)**: If native WebSockets are not available, Velox must support **SIP Trunking** with standard codecs (G.711u/a), which we can then route through a gateway like Vapi or Retell.

## 4. Virtual Phone Numbers
*   **Provisioning**: Ability to purchase or use existing Velox numbers for programmable voice.
*   **Caller ID**: Support for setting valid Caller IDs on outbound calls.

## 5. Technical Documentation Links
Please ask for or find documentation links for:
*   *Programmable Voice API Quickstart*
*   *WebSocket Media Streaming Guide* (if available)
*   *Webhook / Callback Event Reference*

---
> [!NOTE]
> Integrating a new provider usually requires creating an "Adapter" in our backend logic (`main.py`) to handle their specific JSON formats for events and audio streaming.
