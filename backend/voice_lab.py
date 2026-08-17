import os
import uvicorn
import asyncio
import json
import base64
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Rio Voice Lab 🧪")

HTML_UI = """
<!DOCTYPE html>
<html>
<head>
    <title>Rio Voice Lab 🧪</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        .glass { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); }
        .gradient-text { background: linear-gradient(to right, #8b5cf6, #3b82f6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex items-center justify-center p-4">
    <div class="max-w-2xl w-full space-y-8">
        <div class="text-center">
            <h1 class="text-5xl font-black gradient-text">VOICE LAB</h1>
            <p class="text-slate-400 mt-2">Zero-Latency AI Agent Research Tool</p>
        </div>

        <div class="glass rounded-3xl p-8 space-y-6">
            <div class="flex items-center justify-between">
                <div>
                    <h3 class="text-xl font-bold">Deepgram Voice Agent</h3>
                    <p class="text-sm text-slate-500">All-in-one conversational engine</p>
                </div>
                <div id="status-dot" class="h-3 w-3 rounded-full bg-slate-700"></div>
            </div>

            <div class="flex flex-col items-center py-8">
                <button id="main-btn" class="h-24 w-24 rounded-full bg-indigo-600 hover:bg-indigo-500 shadow-lg shadow-indigo-500/50 flex items-center justify-center transition-all hover:scale-105 active:scale-95 group">
                    <svg id="mic-icon" class="h-10 w-10 text-white group-hover:animate-pulse" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-20a3 3 0 00-3 3v1h6V7a3 3 0 00-3-3z" />
                    </svg>
                    <div id="stop-icon" class="hidden h-8 w-8 bg-white rounded-sm"></div>
                </button>
                <p id="hint" class="mt-4 text-sm font-medium text-slate-400">Press to start testing</p>
            </div>

            <div class="space-y-2">
                <label class="text-xs font-bold text-slate-500 uppercase">Live Interaction</label>
                <div id="logs" class="h-48 overflow-y-auto rounded-xl bg-slate-900/50 p-4 font-mono text-xs space-y-2 border border-white/5">
                    <div class="text-indigo-400">[Lab]: Ready for testing...</div>
                </div>
            </div>
        </div>

        <div class="grid grid-cols-2 gap-4 text-center text-[10px] font-bold text-slate-600 uppercase">
          <div class="p-4 glass rounded-2xl">⚡ 300ms End-to-End</div>
          <div class="p-4 glass rounded-2xl">🎙️ Native Audio Pipeline</div>
        </div>
    </div>

    <script>
        let ws;
        let audioCtx;
        let processor;
        let isConnected = false;

        const mainBtn = document.getElementById('main-btn');
        const micIcon = document.getElementById('mic-icon');
        const stopIcon = document.getElementById('stop-icon');
        const statusDot = document.getElementById('status-dot');
        const hint = document.getElementById('hint');
        const logs = document.getElementById('logs');

        function log(msg, color = "text-indigo-400") {
            const div = document.createElement('div');
            div.className = color;
            div.textContent = `[Lab]: ${msg}`;
            logs.appendChild(div);
            logs.scrollTop = logs.scrollHeight;
        }

        async function start() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                ws = new WebSocket(`ws://${window.location.host}/stream`);
                ws.binaryType = "arraybuffer";

                ws.onopen = () => {
                    log("Connected to local lab", "text-emerald-400");
                    statusDot.className = "h-3 w-3 rounded-full bg-emerald-500 animate-pulse";
                    isConnected = true;
                    micIcon.classList.add('hidden');
                    stopIcon.classList.remove('hidden');
                    hint.textContent = "I'm listening...";
                };

                ws.onmessage = async (event) => {
                  if (typeof event.data === 'string') {
                    const data = json.parse(event.data);
                    if (data.type === 'transcript') {
                        log(`Rio: ${data.text}`, "text-slate-100");
                    }
                  } else {
                    // Audio payload (PCM)
                    playAudio(event.data);
                  }
                };

                ws.onclose = () => stop();

                // Setup Audio Context
                audioCtx = new AudioContext({ sampleRate: 16000 });
                const source = audioCtx.createMediaStreamSource(stream);
                processor = audioCtx.createScriptProcessor(4096, 1, 1);

                source.connect(processor);
                processor.connect(audioCtx.destination);

                processor.onaudioprocess = (e) => {
                    if (ws.readyState === WebSocket.OPEN) {
                        const input = e.inputBuffer.getChannelData(0);
                        // Convert to Int16
                        const out = new Int16Array(input.length);
                        for(let i=0; i<input.length; i++) {
                            out[i] = Math.max(-1, Math.min(1, input[i])) * 0x7FFF;
                        }
                        ws.send(out.buffer);
                    }
                };

            } catch (err) {
                log(`Error: ${err.message}`, "text-red-400");
            }
        }

        function stop() {
            if (ws) ws.close();
            if (processor) processor.disconnect();
            if (audioCtx) audioCtx.close();
            
            isConnected = false;
            micIcon.classList.remove('hidden');
            stopIcon.classList.add('hidden');
            statusDot.className = "h-3 w-3 rounded-full bg-slate-700";
            hint.textContent = "Session ended";
            log("Session stopped");
        }

        let nextStartTime = 0;
        function playAudio(buffer) {
            if (!audioCtx) return;
            audioCtx.decodeAudioData(buffer, (audioBuffer) => {
              const source = audioCtx.createBufferSource();
              source.buffer = audioBuffer;
              source.connect(audioCtx.destination);
              const startTime = Math.max(audioCtx.currentTime, nextStartTime);
              source.start(startTime);
              nextStartTime = startTime + audioBuffer.duration;
            });
        }

        mainBtn.onclick = () => isConnected ? stop() : start();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return HTML_UI

@app.websocket("/stream")
async def handle_stream(websocket: WebSocket):
    await websocket.accept()
    
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        await websocket.send_text(json.dumps({"type": "error", "message": "DEEPGRAM_API_KEY missing"}))
        await websocket.close()
        return

    print("🚀 Voice Lab: Client connected. Opening Deepgram Agent...")

    # Deepgram Voice Agent WebSocket: Correct V1 Endpoint
    voice = os.getenv("DEEPGRAM_VOICE", "aura-asteria-en")
    # Deepgram Voice Agent WebSocket: Correct V1 Endpoint
    uri = f"wss://agent.deepgram.com/v1/agent/converse?model=nova-2&voice={voice}&encoding=linear16&sample_rate=16000"
    
    headers = {"Authorization": f"Token {api_key}"}
    
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(uri, headers=headers) as dg_ws:
            
            # 1. INITIAL CONFIGURATION
            config = {
                "type": "SettingsConfiguration",
                "audio": {
                    "input": {
                        "encoding": "linear16",
                        "sample_rate": 16000
                    },
                    "output": {
                        "encoding": "linear16",
                        "sample_rate": 16000,
                        "container": "none"
                    }
                },
                "agent": {
                    "listen": {"model": "nova-2"},
                    "speak": {"model": "aura-asteria-en"},
                    "think": {
                        "provider": {"type": "open_ai"},
                        "model": "gpt-4o-mini",
                        "instructions": "You are a helpful, extremely concise assistant. Reply in one short sentence."
                    }
                }
            }
            await dg_ws.send_json(config)
            print("⚙️ Voice Lab: Agent configuration sent.")

            async def sender():
                try:
                    while True:
                        data = await websocket.receive_bytes()
                        await dg_ws.send_bytes(data)
                except Exception:
                    pass

            async def receiver():
                try:
                    async for msg in dg_ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            res = json.loads(msg.data)
                            # Deepgram Agent returns text/events as well
                            if "transcript" in res:
                                await websocket.send_text(json.dumps({
                                    "type": "transcript",
                                    "text": res["transcript"]
                                }))
                        elif msg.type == aiohttp.WSMsgType.BINARY:
                            # Direct synthesis audio from Deepgram
                            await websocket.send_bytes(msg.data)
                except Exception:
                    pass

            await asyncio.gather(sender(), receiver())

if __name__ == "__main__":
    import aiohttp
    print("🧪 Rio Voice Lab starting on http://localhost:8080")
    uvicorn.run(app, host="0.0.0.0", port=8080)
