import os
import json
import base64
import asyncio
import aiohttp
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Rio Phone Lab 📱")

# CONFIGURATION

DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")

@app.api_route("/voice", methods=["GET", "POST"])
async def voice_webhook(request: Request):
    """Twilio Webhook: Initial call entry point."""
    host = request.headers.get("host")
    protocol = "wss" if "localhost" not in host else "ws"
    
    # Minimal TwiML to connect to our Stream
    return HTMLResponse(
        content=f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say>Connecting to the experiment, please wait.</Say>
            <Connect>
                <Stream url="{protocol}://{host}/media-stream" />
            </Connect>
        </Response>""",
        media_type="application/xml"
    )

@app.websocket("/media-stream")
async def handle_media_stream(websocket: WebSocket):
    """Twilio Media Stream WebSocket: Real-time Audio Relay."""
    await websocket.accept()
    print("📱 Phone Lab: Twilio connected. Opening Deepgram Agent...")

    # DG Agent URL (Production V1)
    # Using PCMU (mulaw) to match Twilio's native format (8kHz)
    voice = os.getenv("DEEPGRAM_VOICE", "aura-asteria-en")
    dg_url = f"wss://agent.deepgram.com/v1/agent/converse?model=nova-2&voice={voice}&encoding=mulaw&sample_rate=8000"
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(dg_url, headers=headers) as dg_ws:
            
            # 1. INITIAL HANDSHAKE
            # We use Deepgram-hosted LLM (mistral-small) to ensure stability
            config = {
                "type": "SettingsConfiguration",
                "audio": {
                    "input": {"encoding": "mulaw", "sample_rate": 8000},
                    "output": {"encoding": "mulaw", "sample_rate": 8000, "container": "none"}
                },
                "agent": {
                    "listen": {"model": "nova-2"},
                    "speak": {"model": "aura-asteria-en"},
                    "think": {
                        "provider": {"type": "deepgram"},
                        "model": "mistral-small",
                        "instructions": "You are a helpful, extremely concise assistant. Reply in one short sentence or one word if possible."
                    }
                }
            }
            await dg_ws.send_json(config)
            print("⚙️ Phone Lab: Agent configuration sent.")

            # Mutable container to share streamSid between tasks
            state = {"sid": None}

            async def twilio_to_dg():
                try:
                    async for message in websocket.iter_text():
                        data = json.loads(message)
                        if data["event"] == "start":
                            state["sid"] = data["start"]["streamSid"]
                            print(f"📱 Phone Lab: Stream started. SID: {state['sid']}")
                        elif data["event"] == "media":
                            payload = base64.b64decode(data["media"]["payload"])
                            await dg_ws.send_bytes(payload)
                        elif data["event"] == "stop":
                            print("📱 Phone Lab: Twilio stop event.")
                            break
                except Exception as e:
                    print(f"❌ Error relaying Twilio -> DG: {e}")

            async def dg_to_twilio():
                try:
                    async for msg in dg_ws:
                        if msg.type == aiohttp.WSMsgType.BINARY and state["sid"]:
                            # Received raw mulaw from Deepgram synthesis
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
                            if "transcript" in res:
                                print(f"Speech: {res['transcript']}")
                except Exception as e:
                    print(f"❌ Error relaying DG -> Twilio: {e}")

            await asyncio.gather(twilio_to_dg(), dg_to_twilio())

if __name__ == "__main__":
    import uvicorn
    print("\n🚀 Rio Phone Lab is live!")
    print("1. Point Twilio Voice Webhook to: http://your-ngrok-url/voice")
    print("2. Call your Twilio number.\n")
    uvicorn.run(app, host="0.0.0.0", port=8081)
