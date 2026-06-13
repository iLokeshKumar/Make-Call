import asyncio
import base64
import json
import logging
import time
import aiohttp

logger = logging.getLogger(__name__)

# Inworld TTS — bidirectional WebSocket streaming
# Docs: https://docs.inworld.ai/tts/synthesize-speech-websocket
# Auth: Authorization: Basic {api_key}
# URL:  wss://api.inworld.ai/tts/v1/voice:streamBidirectional
# Flow:
#   1. Connect with Basic auth header
#   2. Send createContext (voiceId, modelId, audioConfig with MULAW 8kHz)
#   3. Wait for contextCreated response
#   4. Send sendText messages
#   5. Send flushContext to trigger synthesis
#   6. Receive audioChunk messages (base64 MULAW) + flushCompleted
#   7. Send closeContext when done

_WS_URL = "wss://api.inworld.ai/tts/v1/voice:streamBidirectional"


class InworldTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Inworld"
        self.voice_id = voice_id or "inworld-asteria-en"
        self.api_key = api_key
        self.model = model or "inworld-tts-1"
        self.last_latency = 0

        if not self.api_key:
            logger.warning("InworldTTS initialized without API key — streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [InworldTTS] API key missing.")
            return

        start_time = time.time()
        first_byte_time = 0
        headers = {"Authorization": f"Basic {self.api_key}"}

        async def _stream_on_ws(ws):
            nonlocal first_byte_time
            context_id = f"ctx_{int(time.time() * 1000)}"
            state = "init"  # init → audio → done

            await ws.send_json({
                "createContext": {
                    "contextId": context_id,
                    "voiceId": self.voice_id,
                    "modelId": self.model,
                    "audioConfig": {
                        "audioEncoding": "MULAW",
                        "sampleRateHertz": 8000,
                    },
                }
            })

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    logger.info("[InworldTTS] RAW state=%s: %s", state, msg.data)
                    data = json.loads(msg.data)

                    if state == "init":
                        if "contextCreated" in data:
                            state = "audio"
                            await ws.send_json({"sendText": {"contextId": context_id, "text": text}})
                            await ws.send_json({"flushContext": {"contextId": context_id}})
                        elif "error" in data:
                            logger.error("[InworldTTS] context error: %s", data)
                            return

                    elif state == "audio":
                        chunk = data.get("audioChunk") or {}
                        audio_b64 = chunk.get("audio") or chunk.get("content") or data.get("audio")
                        if audio_b64:
                            if first_byte_time == 0:
                                first_byte_time = time.time() - start_time
                            mulaw = base64.b64decode(audio_b64)
                            await communicator.send_media(base64.b64encode(mulaw).decode())
                        if "flushCompleted" in data:
                            break
                        if "error" in data:
                            logger.error("[InworldTTS] synthesis error: %s", data)
                            break

                elif msg.type == aiohttp.WSMsgType.BINARY:
                    if first_byte_time == 0:
                        first_byte_time = time.time() - start_time
                    await communicator.send_media(base64.b64encode(msg.data).decode())
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning("[InworldTTS] WS closed state=%s code=%s", state, msg.data)
                    break

            try:
                if not ws.closed:
                    await ws.send_json({"closeContext": {"contextId": context_id}})
            except Exception:
                pass

        try:
            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                session = aiohttp_session or aiohttp.ClientSession()
                owned = aiohttp_session is None
                try:
                    async with session.ws_connect(_WS_URL, headers=headers) as ws:
                        await _stream_on_ws(ws)
                finally:
                    if owned:
                        await session.close()

            self.last_latency = first_byte_time
            logger.info("[InworldTTS] Done. First byte: %.3fs", first_byte_time)
        except Exception as exc:
            logger.error("❌ [InworldTTS] Error: %s", exc, exc_info=True)
