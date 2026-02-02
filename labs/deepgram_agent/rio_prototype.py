import os
import json
import base64
import asyncio
import aiohttp
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

# Load keys
load_dotenv(dotenv_path="../../backend/.env")

app = FastAPI(title="Rio 3.0: All-in-One Voice Prototype ⚡")

# CONFIGURATION
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# MODERN BROWSER UI (PREMIUM REALTIME DESIGN)
BROWSER_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rio 3.0 Prototype ⚡</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;700&display=swap" rel="stylesheet">
    <style>
        body { font-family: 'Outfit', sans-serif; }
        .orb {
            width: 200px; height: 200px;
            background: radial-gradient(circle, #8b5cf6 0%, #3b82f6 100%);
            filter: blur(40px); opacity: 0.6;
            animation: pulse 4s infinite ease-in-out;
        }
        @keyframes pulse { 0% { scale: 1; opacity: 0.4; } 50% { scale: 1.2; opacity: 0.7; } 100% { scale: 1; opacity: 0.4; } }
        .glass { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(15px); border: 1px solid rgba(255, 255, 255, 0.1); }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center overflow-hidden">
    <div class="orb absolute"></div>
    
    <div class="relative z-10 w-full max-w-lg p-8 glass rounded-3xl shadow-2xl text-center space-y-8">
        <div>
            <h1 class="text-4xl font-bold tracking-tight">Rio 3.0 <span class="text-indigo-400">Prototype</span></h1>
            <p class="text-slate-400 text-sm mt-2 font-light">All-in-One Voice Brain (Deepgram + Gemini)</p>
        </div>

        <div class="flex justify-center">
            <button id="mic-btn" class="group relative">
                <div id="ring" class="absolute -inset-2 bg-indigo-500 rounded-full opacity-0 blur group-hover:opacity-50 transition duration-500"></div>
                <div id="btn-inner" class="relative h-28 w-28 bg-slate-900 rounded-full flex items-center justify-center border-2 border-slate-800 transition-all hover:border-indigo-500">
                    <svg id="mic-icon" class="w-12 h-12 text-slate-400 group-hover:text-indigo-400 transition-colors" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-20a3 3 0 00-3 3v1h6V7a3 3 0 00-3-3z" />
                    </svg>
                    <div id="stop-icon" class="hidden h-10 w-10 bg-indigo-500 rounded-lg animate-pulse"></div>
                </div>
            </button>
        </div>

        <div id="status" class="text-xs font-bold text-slate-500 uppercase tracking-widest">System Ready</div>

        <div class="space-y-4">
            <div id="transcript-user" class="text-slate-100 font-medium min-h-[1.5em] italic"></div>
            <div id="transcript-ai" class="text-indigo-400 font-bold text-xl min-h-[1.5em]"></div>
        </div>

        <div class="pt-4 border-t border-white/5 grid grid-cols-2 gap-4 text-[10px] font-bold text-slate-600 uppercase">
            <div class="p-4 bg-slate-900/50 rounded-2xl border border-white/5">
                <p>Phone Webhook</p>
                <p class="text-slate-400 mt-1">/voice</p>
            </div>
            <div class="p-4 bg-slate-900/50 rounded-2xl border border-white/5">
                <p>Architecture</p>
                <p class="text-slate-400 mt-1">Unified Stream</p>
            </div>
        </div>
    </div>

    <script>
        let ws;
        let audioCtx;
        let processor;
        let isRecording = false;

        const micBtn = document.getElementById('mic-btn');
        const micIcon = document.getElementById('mic-icon');
        const stopIcon = document.getElementById('stop-icon');
        const statusEl = document.getElementById('status');
        const tUser = document.getElementById('transcript-user');
        const tAi = document.getElementById('transcript-ai');
        const ring = document.getElementById('ring');

        async function start() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                ws = new WebSocket(`ws://${window.location.host}/browser-stream`);
                ws.binaryType = "arraybuffer";

                ws.onopen = () => {
                    statusEl.textContent = "CONNECTED - SPEAK NOW";
                    statusEl.className = "text-xs font-bold text-emerald-500 uppercase tracking-widest";
                    ring.style.opacity = "1";
                    micIcon.classList.add('hidden');
                    stopIcon.classList.remove('hidden');
                    isRecording = true;
                };

                ws.onmessage = async (event) => {
                    if (typeof event.data === 'string') {
                        const data = JSON.parse(event.data);
                        if (data.type === 'user') tUser.textContent = `You: ${data.text}`;
                        if (data.type === 'ai') tAi.textContent = data.text;
                    } else {
                        playAudio(event.data);
                    }
                };

                ws.onclose = () => stop();

                audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
                const source = audioCtx.createMediaStreamSource(stream);
                processor = audioCtx.createScriptProcessor(4096, 1, 1);

                source.connect(processor);
                processor.connect(audioCtx.destination);

                processor.onaudioprocess = (e) => {
                    if (ws.readyState === WebSocket.OPEN) {
                        const input = e.inputBuffer.getChannelData(0);
                        const out = new Int16Array(input.length);
                        for(let i=0; i<input.length; i++) {
                            out[i] = Math.max(-1, Math.min(1, input[i])) * 0x7FFF;
                        }
                        ws.send(out.buffer);
                    }
                };
            } catch (err) { alert("Mic error: " + err.message); }
        }

        function stop() {
            if (ws) ws.close();
            if (processor) processor.disconnect();
            if (audioCtx) audioCtx.close();
            isRecording = false;
            micIcon.classList.remove('hidden');
            stopIcon.classList.add('hidden');
            ring.style.opacity = "0";
            statusEl.textContent = "System Ready";
            statusEl.className = "text-xs font-bold text-slate-500 uppercase tracking-widest";
        }

        let nextStartTime = 0;
        function playAudio(buffer) {
            audioCtx.decodeAudioData(buffer, (audioBuffer) => {
                const source = audioCtx.createBufferSource();
                source.buffer = audioBuffer;
                source.connect(audioCtx.destination);
                const startTime = Math.max(audioCtx.currentTime, nextStartTime);
                source.start(startTime);
                nextStartTime = startTime + audioBuffer.duration;
            });
        }

        micBtn.onclick = () => isRecording ? stop() : start();
    </script>
</body>
</html>
"""

# API ROUTES

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return BROWSER_UI

@app.api_route("/voice", methods=["GET", "POST"])
async def voice_webhook(request: Request):
    """Twilio Webhook: Phone Call Entry."""
    host = request.headers.get("host")
    protocol = "wss" if "localhost" not in host else "ws"
    twi_ml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Connect><Stream url="{protocol}://{host}/phone-stream" /></Connect>
    </Response>"""
    return HTMLResponse(content=twi_ml, media_type="application/xml")

# CORE AGENT LOGIC (THE UNIFIED BRAIN)

async def connect_to_deepgram_agent(client_ws: WebSocket, encoding: str, sample_rate: int):
    """
    Connects to Deepgram's native Voice-to-Voice API.
    Handles STT + LLM + TTS in ONE stream.
    """
    if not DEEPGRAM_API_KEY:
        await client_ws.send_text(json.dumps({"type": "ai", "text": "Error: DEEPGRAM_API_KEY missing"}))
        return

    dg_url = f"wss://agent.deepgram.com/v1/agent/converse?model=nova-2&voice=aura-2-odysseus-en&encoding={encoding}&sample_rate={sample_rate}"
    headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(dg_url, headers=headers) as dg_ws:
            print(f"🚀 Brain: Unified Voice Session started ({encoding}/{sample_rate}Hz)")

            # CONFIGURATION HANDSHAKE
            config = {
                "type": "SettingsConfiguration",
                "audio": {
                    "input": {"encoding": encoding, "sample_rate": sample_rate},
                    "output": {"encoding": encoding, "sample_rate": sample_rate, "container": "none"}
                },
                "agent": {
                    "listen": {"model": "flux-general-en"},
                    "speak": {"model": "aura-2-odysseus-en"},
                    "think": {
                        "provider": {"type": "google", "key": GEMINI_API_KEY},
                        "model": "gemini-1.5-flash",
                        "instructions": "You are Rio 3.0, a sales genius. You respond natively in voice. Be extremely concise (1-word or 1-sentence). No chat filler."
                    }
                }
            }
            await dg_ws.send_json(config)

            async def from_client():
                """Client Audio -> Deepgram Agent"""
                try:
                    while True:
                        msg = await client_ws.receive()
                        if msg["type"] == "websocket.receive":
                            if "bytes" in msg:
                                await dg_ws.send_bytes(msg["bytes"])
                            elif "text" in msg:
                                data = json.loads(msg["text"])
                                if data.get("event") == "media": # Twilio
                                    payload = base64.b64decode(data["media"]["payload"])
                                    await dg_ws.send_bytes(payload)
                                elif data.get("event") == "stop": break
                except Exception as e: print(f"Client disconnected: {e}")

            async def from_agent():
                """Deepgram Agent -> Client (Final Audio + Transcripts)"""
                stream_sid = None
                try:
                    # Share streamSid between messages for Twilio
                    async for msg in dg_ws:
                        if msg.type == aiohttp.WSMsgType.BINARY:
                            if encoding == "mulaw": # Twilio
                                if stream_sid:
                                    res = {"event":"media","streamSid":stream_sid,"media":{"payload":base64.b64encode(msg.data).decode()}}
                                    await client_ws.send_text(json.dumps(res))
                            else: # Browser
                                await client_ws.send_bytes(msg.data)
                        
                        elif msg.type == aiohttp.WSMsgType.TEXT:
                            res = json.loads(msg.data)
                            if "transcript" in res:
                                await client_ws.send_text(json.dumps({"type":"user","text":res["transcript"]}))
                            if "text" in res:
                                await client_ws.send_text(json.dumps({"type":"ai","text":res["text"]}))
                            if res.get("event") == "start": stream_sid = res["start"]["streamSid"] # Twilio logic
                except Exception as e: print(f"Agent stream error: {e}")

            await asyncio.gather(from_client(), from_agent())

# WEBSOCKET HANDLERS

@app.websocket("/browser-stream")
async def browser_stream(websocket: WebSocket):
    await websocket.accept()
    await connect_to_deepgram_agent(websocket, "linear16", 16000)

@app.websocket("/phone-stream")
async def phone_stream(websocket: WebSocket):
    await websocket.accept()
    # Need to catch the initial 'start' event from Twilio to get Sid
    try:
        first_msg = await websocket.receive_json()
        sid = first_msg["start"]["streamSid"]
        print(f"📞 Phone: Session started. SID: {sid}")
        # Re-inject SID logic or pass it. For simplicity, we detect it in the loop.
        await connect_to_deepgram_agent(websocket, "mulaw", 8000)
    except Exception as e: print(f"Phone error: {e}")

if __name__ == "__main__":
    import uvicorn
    print("\n--- RIO 3.0 ALL-IN-ONE PROTOTYPE ---")
    print("BROWSER: http://localhost:8082 (No ngrok needed!)")
    print("PHONE:   [Ngrok URL]/voice")
    uvicorn.run(app, host="0.0.0.0", port=8082)
