import asyncio
import json
import logging
import audioop
from typing import AsyncGenerator, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)

# ink-2   → English-only, streaming WebSocket turns endpoint (low-latency)
# ink-whisper → multilingual, REST utterance-by-utterance (via CartesiaSTTHelper)

_WS_URL = "wss://api.cartesia.ai/stt/turns/websocket"
_CARTESIA_VERSION = "2025-04-16"
_WS_MODELS = {"ink-2"}


class CartesiaSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Cartesia"
        self.model = model or "ink-whisper"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("CartesiaSTT initialized without API key — transcription will fail.")

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "pcm_mulaw",
        sample_rate: int = 8000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [CartesiaSTT] API key missing.")
            yield {"transcript": "[Error: Cartesia API Key Missing]", "is_final": True}
            return

        if self.model in _WS_MODELS:
            async for result in self._transcribe_ws(audio_generator, encoding, sample_rate):
                yield result
        else:
            async for result in self._transcribe_rest(audio_generator, encoding, sample_rate):
                yield result

    # ── ink-2: WebSocket turns endpoint ──────────────────────────────────────

    async def _transcribe_ws(
        self,
        audio_generator,
        encoding: str,
        sample_rate: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        # Cartesia WS auth: api_key + version in URL (same pattern as TTS WebSocket).
        # Config also goes in URL params — server closes immediately if sent as a frame.
        # Mulaw 8kHz → linear16 8kHz. No upsample: ratecv 8k→16k only adds
        # interpolated silence — the source bandwidth is still 4kHz (telephone).
        # Cartesia ink-2 accepts 8kHz PCM natively, so declare the true rate.
        is_mulaw = "mulaw" in encoding
        out_sample_rate = sample_rate  # send at native rate, no artificial upsample
        url = (
            f"{_WS_URL}"
            f"?api_key={self.api_key}"
            f"&cartesia_version={_CARTESIA_VERSION}"
            f"&model={self.model}"
            f"&language=en"
            f"&encoding=pcm_s16le"
            f"&sample_rate={out_sample_rate}"
        )
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(url) as ws:
                    logger.info("[CartesiaSTT/ws] Connected — model=%s sample_rate=%s", self.model, out_sample_rate)

                    async def _sender():
                        try:
                            async for chunk in audio_generator:
                                if not chunk:
                                    continue
                                if ws.closed:
                                    break
                                # Mulaw → linear16 at native rate. No upsampling.
                                pcm = audioop.ulaw2lin(chunk, 2) if is_mulaw else chunk
                                await ws.send_bytes(pcm)
                            if not ws.closed:
                                await ws.close()
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _msg = str(exc).lower()
                            if "closing" in _msg or "closed" in _msg:
                                logger.debug("[CartesiaSTT/ws] WS closed during send — expected at call end")
                            else:
                                logger.error("[CartesiaSTT/ws] Send error: %s", exc)

                    send_task = asyncio.create_task(_sender())
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                msg_type = data.get("type", "")
                                if msg_type == "transcript":
                                    text = (data.get("transcript") or data.get("text") or "").strip()
                                    is_final = data.get("is_final", False)
                                    if text:
                                        yield {"transcript": text, "is_final": is_final, "type": "transcript"}
                                elif msg_type == "turn_end":
                                    text = (data.get("transcript") or "").strip()
                                    if text:
                                        yield {"transcript": text, "is_final": True, "type": "transcript"}
                                elif msg_type == "error":
                                    logger.error(
                                        "[CartesiaSTT/ws] Server error — model=%s code=%s msg=%s",
                                        self.model, data.get("code"), data.get("message"),
                                    )
                                    break
                                elif msg_type == "done":
                                    break
                            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                                break
                    finally:
                        send_task.cancel()

            except Exception as exc:
                logger.error("[CartesiaSTT/ws] Error — model=%s: %s", self.model, exc, exc_info=True)

    # ── ink-whisper: REST utterance endpoint (multilingual) ──────────────────

    async def _transcribe_rest(
        self,
        audio_generator,
        encoding: str,
        sample_rate: int,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        from services.ai.cartesia_stt import CartesiaSTT as CartesiaSTTHelper

        helper = CartesiaSTTHelper(api_key=self.api_key, model=self.model)
        resample_state = None

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
                if helper.process_chunk(pcm):
                    transcript = await helper.transcribe()
                    if transcript:
                        yield {"transcript": transcript, "is_final": True, "type": "transcript"}

            # Flush any remaining speech
            if helper._speech_buffer:
                transcript = await helper.transcribe()
                if transcript:
                    yield {"transcript": transcript, "is_final": True, "type": "transcript"}

        except Exception as exc:
            logger.error("[CartesiaSTT/rest] Error — model=%s: %s", self.model, exc, exc_info=True)
