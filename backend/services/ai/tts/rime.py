import asyncio
import base64
import json
import logging
import time
import aiohttp
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

# Rime TTS — JSON WebSocket streaming
# Docs: https://docs.rime.ai/docs/websockets
# Auth: Authorization: Bearer {api_key}
# URL:  wss://users-ws.rime.ai/ws3?speaker={voice}&modelId={model}&audioFormat=mulaw&samplingRate=8000
# Flow:
#   1. Connect with Bearer auth + query params (speaker, modelId, audioFormat, samplingRate)
#   2. Send {"text": "..."} — server buffers until punctuation then synthesizes
#   3. Receive {"type": "chunk", "data": "base64-mulaw"}
#   4. Receive {"type": "done"} when synthesis complete
#   5. Send {"operation": "eos"} to end session

_WS_BASE = "wss://users-ws.rime.ai/ws3"


class RimeTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Rime"
        self.model = model or "coda"
        self.voice_id = voice_id or "astra"
        self.api_key = api_key
        self.last_latency = 0

        if not self.api_key:
            logger.warning("RimeTTS initialized without API key — streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [RimeTTS] API key missing.")
            return

        start_time = time.time()
        first_byte_time = 0

        params = urlencode({
            "speaker": self.voice_id,
            "modelId": self.model,
            "audioFormat": "mulaw",
            "samplingRate": 8000,
            "segment": "bySentence",
        })
        url = f"{_WS_BASE}?{params}"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        async def _stream_on_ws(ws):
            nonlocal first_byte_time

            # Send text
            await ws.send_json({"text": text})
            # Flush buffer so single-chunk text without trailing punctuation gets synthesized
            await ws.send_json({"operation": "flush"})

            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    msg_type = data.get("type", "")

                    if msg_type == "chunk":
                        audio_b64 = data.get("data") or data.get("audio")
                        if audio_b64:
                            if first_byte_time == 0:
                                first_byte_time = time.time() - start_time
                            await communicator.send_media(audio_b64)
                    elif msg_type == "done":
                        break
                    elif msg_type == "error":
                        logger.error("[RimeTTS] Server error: %s", data)
                        break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    # Raw binary path (ws endpoint) — unlikely on ws3 but handle it
                    if first_byte_time == 0:
                        first_byte_time = time.time() - start_time
                    await communicator.send_media(base64.b64encode(msg.data).decode())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.warning("[RimeTTS] WS closed — code=%s reason=%r", msg.data, msg.extra)
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error("[RimeTTS] WS error — code=%s reason=%r", msg.data, msg.extra)
                    break

            # Signal end of session
            try:
                if not ws.closed:
                    await ws.send_json({"operation": "eos"})
            except Exception:
                pass

        try:
            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                session = aiohttp_session or aiohttp.ClientSession()
                owned = aiohttp_session is None
                try:
                    async with session.ws_connect(url, headers=headers) as ws:
                        await _stream_on_ws(ws)
                finally:
                    if owned:
                        await session.close()

            self.last_latency = first_byte_time
            logger.info("[RimeTTS] Done. First byte: %.3fs", first_byte_time)
        except Exception as exc:
            logger.error("❌ [RimeTTS] Error: %s", exc, exc_info=True)
