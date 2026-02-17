import os
import json
import base64
import asyncio
import aiohttp
import traceback
from fastapi import FastAPI, WebSocket, Request, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from dotenv import load_dotenv

# Load keys
load_dotenv(dotenv_path="../../backend/.env")

app = FastAPI(title="Rio 1.0: All-in-One Voice Prototype ⚡")

BROWSER_UI = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rio 1.0 Prototype ⚡</title>
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
            <h1 class="text-4xl font-bold tracking-tight">Rio 1.0 <span class="text-indigo-400">Prototype</span></h1>
            <p class="text-slate-400 text-sm mt-2 font-light">All-in-One Voice Brain (Deepgram)</p>
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
    print("Phone: [Incoming Call] Webhook triggered /voice")
    host = request.headers.get("host")
    protocol = "wss" if "localhost" not in host else "ws"
    ws_url = f"{protocol}://{host}/phone-stream"
    print(f"Phone: [Twilio] TwiML Stream URL: {ws_url}")
    twi_ml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Connect><Stream url="{ws_url}" /></Connect></Response>'
    return HTMLResponse(content=twi_ml, media_type="application/xml")

# CORE AGENT LOGIC (THE UNIFIED BRAIN)

from deepgram import DeepgramClient
from deepgram import AsyncDeepgramClient
from deepgram.core.events import EventType

import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

from backend.agents.graph_agent import app as graph_app
from langchain_core.messages import HumanMessage

async def connect_to_deepgram_agent(client_ws: WebSocket, encoding: str, sample_rate: int, stream_sid: str = None):
    """
    Manually orchestrates STT -> LangGraph -> TTS.
    Deepgram Listen (STT) -> Python (Graph) -> Deepgram Speak (TTS)
    """
    api_key = os.getenv("DEEPGRAM_API_KEY")
    if not api_key:
        await client_ws.send_text(json.dumps({"type": "ai", "text": "Error: DEEPGRAM_API_KEY missing"}))
        return

    # Initialize Deepgram Client with 5-minute timeout to prevent ReadTimeout
    deepgram = AsyncDeepgramClient(api_key=api_key, timeout=300)
    
    # TTS Helper
    async def speak_text(text: str):
        """Converts text to speech and streams back to client."""
        try:
            # Fetch dynamic TTS model from database
            from backend.database import Session, select, SystemSettings, engine
            with Session(engine) as session:
                tts_setting = session.exec(select(SystemSettings).where(SystemSettings.key == "tts_model")).first()
                model_name = tts_setting.value if tts_setting else "aura-asteria-en"
            
            print(f"AI: AI Speaking ({model_name}): {text}")
            
            # Deepgram TTS (REST) - Async Streaming
            options = {
                "model": model_name, 
                "encoding": encoding, 
                "sample_rate": sample_rate
            }
            if encoding == "linear16":
                options["container"] = "wav"
            
            audio_data = bytearray()
            
            # Use async for directly on the generator
            try:
                # deepgram.speak.v1.audio.generate returns an async generator
                # We iterate over it to get bytes
                async for chunk in deepgram.speak.v1.audio.generate(text=text, **options):
                     audio_data.extend(chunk)
            except Exception as e:
                print(f"TTS Generation Error: {e}")
                traceback.print_exc()
                return

            # Send to client
            if encoding == "mulaw" and stream_sid: # Twilio
                 payload = base64.b64encode(audio_data).decode()
                 media_event = {
                     "event": "media",
                     "streamSid": stream_sid,
                     "media": {
                         "payload": payload
                     }
                 }
                 await client_ws.send_text(json.dumps(media_event))
            elif encoding == "linear16": # Browser
                 await client_ws.send_bytes(audio_data)
            
        except Exception as e:
            print(f"TTS Error: {e}")
            traceback.print_exc()

    # Create a unique session ID for LangGraph memory
    import uuid
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    # STT Live Connection
    # Create a websocket connection to Deepgram
    async def process_audio():
        try:
            # Create a websocket connection to Deepgram
            dg_connection_manager = deepgram.listen.v1.connect(
                model="nova-2", 
                language="en-US", 
                smart_format=True, 
                encoding="linear16" if encoding == "linear16" else "mulaw",
                sample_rate=sample_rate
            )

            # Capture loop for thread-safe callbacks
            loop = asyncio.get_running_loop()

            # Handle STT Results
            async def on_message(result, **kwargs):
                try:
                    # [STAGE 3] Deepgram Response
                    if hasattr(result, 'type'):
                        if result.type == "Results":
                            sentence = result.channel.alternatives[0].transcript
                            is_final = result.is_final
                            
                            if len(sentence) > 0:
                                print(f"STT: [STT Result] Final={is_final}: '{sentence}'")
                            
                            if is_final and len(sentence) > 0:
                                # [STAGE 4] Start Thinking
                                print(f"Brain: [STAGE 2] Thinking... (Invoking LangGraph with: {sentence} | Thread: {thread_id})")
                                
                                # Send to Browser UI
                                asyncio.run_coroutine_threadsafe(
                                    client_ws.send_text(json.dumps({"type": "user", "text": sentence})), 
                                    loop
                                )
                                
                                # Use to_thread to prevent blocking the event loop
                                inputs = {"messages": [HumanMessage(content=sentence)]}
                                response = await asyncio.to_thread(graph_app.invoke, inputs, config=config)
                                
                                ai_msg = response["messages"][-1].content
                                # [STAGE 5] Thinking Complete
                                print(f"Brain: [STAGE 3] AI Response Generated: '{ai_msg}'")
                                
                                # 2. Update UI
                                asyncio.run_coroutine_threadsafe(
                                    client_ws.send_text(json.dumps({"type": "ai", "text": ai_msg})),
                                    loop
                                )
                                
                                # 3. Speak
                                # [STAGE 6] Starting TTS
                                print(f"TTS: [STAGE 4] Starting TTS for: '{ai_msg}'")
                                asyncio.run_coroutine_threadsafe(speak_text(ai_msg), loop)
                                
                        elif result.type == "Metadata":
                            print(f"Deepgram: [Deepgram] Metadata Received: {result.request_id}")
                        elif result.type == "UtteranceEnd":
                            print("Deepgram: [Deepgram] Utterance Ended")
                except Exception as e:
                    print(f"Error: [on_message] ERROR: {e}")
                    traceback.print_exc()

            def on_error(error, **kwargs):
                print(f"Error: [Deepgram] ERROR EVENT: {error}")

            def on_close(close, **kwargs):
                print(f"Deepgram: [Deepgram] CLOSED EVENT")

            # Use async context manager
            async with dg_connection_manager as dg_connection:
                # Register Handlers
                dg_connection.on(EventType.MESSAGE, on_message)
                dg_connection.on(EventType.ERROR, on_error)
                dg_connection.on(EventType.CLOSE, on_close)

                # [CRITICAL FIX] Start the listener task to actually receive STT results!
                listen_task = asyncio.create_task(dg_connection.start_listening())

                print(f"Brain: [STAGE 1] Brain: LangGraph Voice Session started ({encoding}/{sample_rate}Hz)")

                # Client Audio Loop
                packet_count = 0
                while True:
                    msg = await client_ws.receive()
                    
                    if msg["type"] == "websocket.disconnect":
                        print("Client: [Client] Disconnected")
                        break

                    if msg["type"] == "websocket.receive":
                        if "bytes" in msg:
                            packet_count += 1
                            if packet_count % 50 == 0:
                                print(f"Audio: [Audio] Received {packet_count} packets ({len(msg['bytes'])} bytes each)")
                            
                            # Send bytes to Deepgram
                            await dg_connection.send_media(msg["bytes"]) 
                        elif "text" in msg:
                            data = json.loads(msg["text"])
                            if data.get("event") == "media": # Twilio
                                payload = base64.b64decode(data["media"]["payload"])
                                await dg_connection.send_media(payload)
                            elif data.get("event") == "stop": 
                                print("Client: [Client] Flow stopped via text event")
                                break
            
        except Exception as e:
            print(f"Deepgram Connection Error: {e}")

    await process_audio()

# WEBSOCKET HANDLERS

@app.websocket("/browser-stream")
async def browser_stream(websocket: WebSocket):
    await websocket.accept()
    await connect_to_deepgram_agent(websocket, "linear16", 16000)

@app.websocket("/phone-stream")
async def phone_stream(websocket: WebSocket):
    await websocket.accept()
    print("📞 Phone: WebSocket accepted")
    try:
        while True:
            msg = await websocket.receive_json()
            if msg.get("event") == "start":
                sid = msg["start"]["streamSid"]
                print(f"Phone: Phone: Session started. SID: {sid}")
                await connect_to_deepgram_agent(websocket, "mulaw", 8000, stream_sid=sid)
                break
            elif msg.get("event") == "connected":
                print("Phone: Phone: Connected event received")
    except Exception as e:
        print(f"Error: Phone WebSocket Error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8082))
    print("\n--- RIO 1.0 ALL-IN-ONE PROTOTYPE ---")
    print(f"URL: http://localhost:{port}")
    print(f"PHONE: [Ngrok URL]/voice")
    uvicorn.run(app, host="0.0.0.0", port=port)
