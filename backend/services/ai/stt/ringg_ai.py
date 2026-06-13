import asyncio
import base64
import json
import logging
import audioop
from typing import AsyncGenerator, Dict, Any

import aiohttp
from tomlkit import ws

logger = logging.getLogger(__name__)

# Ringg.ai real-time streaming STT
# SDK base_url: prod-api.ringg.ai
# Encoding values: int16, linear16, float32, int32
# Events: ready, transcript, ack, pong, error
# Transcript field: "transcription" (not "transcript")
# End stream: {"command": "end"}
_WS_URL = "wss://prod-api.ringg.ai/stt/v1/stream"


class RinggAISTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Ringg"
        self.model = model or "parrot-stt-v1"
        self.api_key = api_key
        self.language = ['en', 'hi']

        if not self.api_key:
            logger.warning("RinggSTT initialized without API key — transcription will fail.")

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "pcm_mulaw",
        sample_rate: int = 8000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [RinggSTT] API key missing.")
            yield {"transcript": "[Error: Ringg API Key Missing]", "is_final": True}
            return

        # Ringg.ai expects a single short language code e.g. "en", "hi"
        _raw_lang = self.language[0] if isinstance(self.language, list) else str(self.language)
        lang = _raw_lang.split("-")[0]

        headers = {"Authorization": f"Bearer {self.api_key}"}
        ws_url = f"{_WS_URL}?sample_rate=16000&encoding=int16&language={lang}&mode=stream"

        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(ws_url, headers=headers) as ws:
                    logger.info("[RinggSTT] Connected — lang=%s", lang)

                    # Send start config first — server waits for this before sending ready
                    await ws.send_str(json.dumps({
                        "type": "start",
                        "api_key": self.api_key,
                        "sample_rate": 16000,
                        "encoding": "int16",
                        "language": lang,
                        "mode": "stream",
                        "enable_cap_punc": True,
                    }))

                    # Wait for ready event before sending audio
                    ready = False
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            logger.info("[RinggSTT] pre-ready: %s", msg.data)
                            evt = data.get("type") or data.get("event", "")
                            if evt == "ready":
                                ready = True
                                break
                            if evt == "error":
                                logger.error("[RinggSTT] Error before ready: %s", data)
                                return
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.error("[RinggSTT] WS closed before ready — code=%s", msg.data)
                            return

                    if not ready:
                        logger.error("[RinggSTT] Never received ready event")
                        return

                    logger.info("[RinggSTT] ready — starting audio stream")
                    resample_state = None

                    async def _sender():
                        nonlocal resample_state
                        try:
                            async for chunk in audio_generator:
                                if not chunk:
                                    continue
                                if "mulaw" in encoding:
                                    pcm = audioop.ulaw2lin(chunk, 2)
                                else:
                                    pcm = chunk
                                if sample_rate != 16000:
                                    pcm, resample_state = audioop.ratecv(
                                        pcm, 2, 1, sample_rate, 16000, resample_state
                                    )
                                await ws.send_bytes(pcm)
                            await ws.send_str(json.dumps({"type": "end"}))
                        except Exception as exc:
                            logger.error("[RinggSTT] Send error: %s", exc)

                    send_task = asyncio.create_task(_sender())
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                evt = data.get("type", "")
                                if evt == "error":
                                    logger.error("[RinggSTT] Server error: %s", data)
                                    break
                                if evt in ("ack", "pong"):
                                    continue
                                _segs = data.get("segments")
                                _seg_text = _segs[0].get("transcription", "") if isinstance(_segs, list) and _segs else ""
                                text = (
                                    data.get("transcription")
                                    or data.get("transcript")
                                    or data.get("text")
                                    or _seg_text
                                ).strip()
                                is_final = bool(data.get("is_final", False))
                                if text:
                                    logger.info("[RinggSTT] transcript final=%s: %r", is_final, text)
                                    yield {"transcript": text, "is_final": is_final, "type": "transcript"}
                                if evt == "end":
                                    break
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    finally:
                        send_task.cancel()

            except Exception as exc:
                logger.error("❌ [RinggSTT] Streaming error: %s", exc, exc_info=True)
