import os
import json
import base64
import asyncio
import aiohttp
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

# Load keys from the main backend .env
load_dotenv(dotenv_path="../../backend/.env")

app = FastAPI(title="Deepgram + Gemini Phone Lab 🧪")

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return """
    <html>
        <head><title>Rio Phone Lab 📱</title></head>
        <body style="font-family: sans-serif; padding: 40px; background: #0f172a; color: #f8fafc; text-align: center;">
            <h1 style="color: #8b5cf6;">🧪 Rio Phone Lab</h1>
            <p>This server is running correctly, but it has no UI because it is a <b>Phone Lab</b>.</p>
            <div style="background: #1e293b; padding: 20px; border-radius: 12px; display: inline-block; margin-top: 20px;">
                <p>Point your Twilio Webhook to:</p>
                <code style="background: #334155; padding: 4px 8px; border-radius: 4px; font-size: 1.2em;">[YOUR-NGROK-URL]/voice</code>
            </div>
            <p style="margin-top: 20px; color: #94a3b8;">Call your Twilio number to start the zero-latency test.</p>
        </body>
    </html>
    """

# ============================================
# CONFIGURATION
# ============================================
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

@app.api_route("/voice", methods=["GET", "POST"])
async def voice_webhook(request: Request):
    """Twilio Webhook: Entry point for the phone call."""
    host = request.headers.get("host")
    protocol = "wss" if "localhost" not in host else "ws"
    
    return HTMLResponse(
        content=f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say>Connecting to Deepgram Gemini Lab.</Say>
            <Connect>
                <Stream url="{protocol}://{host}/media-stream" />
            </Connect>
        </Response>""",
        media_type="application/xml"
    )

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Real-time Audio Relay: Twilio <-> Deepgram Agent."""
    await websocket.accept()
    print("📱 Lab: Phone connected. Opening Deepgram Agent session...")

    # The production V1 Agent endpoint
    dg_url = "wss://agent.deepgram.com/v1/agent/converse"
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(dg_url, headers=headers) as dg_ws:
            
            config = {
                "type": "SettingsConfiguration",
                "audio": {
                    "input": {
                        "encoding": "mulaw",
                        "sample_rate": 8000
                    },
                    "output": {
                        "encoding": "mulaw",
                        "sample_rate": 8000,
                        "container": "none"
                    }
                },
                "agent": {
                    "listen": {
                        "model": "flux-general-en" # Conversational STT
                    },
                    "speak": {
                        "model": "aura-2-odysseus-en" # Aura v2 Voice
                    },
                    "think": {
                        "provider": {
                            "type": "google",
                            "key": GEMINI_API_KEY # Direct Gemini Integration
                        },
                        "model": "gemini-1.5-flash",
                        "instructions": "You are a helpful, ultra-concise assistant. Reply in one short sentence or 1-word. Be lightning fast."
                    }
                }
            }
            
            await dg_ws.send_json(config)
            print("⚙️ Lab: Deepgram Agent configured with Flux + Gemini + Aura 2.")

            state = {"sid": None}

            async def twilio_to_dg():
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data["event"] == "start":
                            state["sid"] = data["start"]["streamSid"]
                            print(f"📡 Lab: Stream started. SID: {state['sid']}")
                        elif data["event"] == "media":
                            payload = base64.b64decode(data["media"]["payload"])
                            await dg_ws.send_bytes(payload)
                        elif data["event"] == "stop":
                            print("🛑 Lab: Twilio hung up.")
                            break
                except Exception as e:
                    print(f"❌ Twilio Loop Error: {e}")

            async def dg_to_twilio():
                try:
                    async for msg in dg_ws:
                        if msg.type == aiohttp.WSMsgType.BINARY and state["sid"]:
                            # Synthesis audio directly from Deepgram
                            twilio_msg = {
                                "event": "media",
                                "streamSid": state["sid"],
                                "media": {
                                    "payload": base64.b64encode(msg.data).decode("utf-8")
                                }
                            }
                            await websocket.send_text(json.dumps(twilio_msg))
                                
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            res = json.loads(msg.data)
                            # Log transcripts and metadata
                            if "transcript" in res:
                                print(f"User: {res['transcript']}")
                            if "text" in res:
                                print(f"Rio: {res['text']}")
                            if res.get("type") == "Error":
                                print(f"⚠️ Deepgram Error: {res.get('message')}")
                                
                except Exception as e:
                    print(f"❌ Deepgram Loop Error: {e}")

            await asyncio.gather(twilio_to_dg(), dg_to_twilio())

if __name__ == "__main__":
    import uvicorn
    print("\n--- DEEPGRAM AGENT LAB ---")
    print("1. Set Twilio Webhook to: [Your Ngrok URL]/voice")
    print("2. Call your number for true zero-latency testing.\n")
    uvicorn.run(app, host="0.0.0.0", port=8082)
