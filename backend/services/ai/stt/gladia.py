import asyncio
import json
import logging
import audioop
from typing import AsyncGenerator, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)

# Gladia real-time streaming STT
# Docs: https://docs.gladia.io/reference/live-audio
# Flow:
#   1. POST https://api.gladia.io/v2/live  →  get {"id": "...", "url": "wss://..."}
#   2. Connect to returned WS URL
#   3. Send binary audio frames (raw, no container)
#   4. Receive JSON transcript events
#
# Valid encodings: wav/pcm, wav/alaw, wav/ulaw
# Twilio/Vobiz stream µ-law at 8 kHz → use wav/ulaw, send raw bytes (no conversion)

_SESSION_URL = "https://api.gladia.io/v2/live"


class GladiaSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Gladia"
        self.model = model or "solaria-1" or "solaria-3"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("GladiaSTT initialized without API key — transcription will fail.")

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "pcm_mulaw",
        sample_rate: int = 8000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [GladiaSTT] API key missing.")
            yield {"transcript": "[Error: Gladia API Key Missing]", "is_final": True}
            return

        is_mulaw = "mulaw" in encoding or "ulaw" in encoding

        if is_mulaw:
            # Send raw µ-law bytes — Gladia decodes them server-side
            gladia_encoding = "wav/ulaw"
            gladia_sample_rate = sample_rate  # typically 8000 from Twilio/Vobiz
            gladia_bit_depth = 8
        else:
            # Linear PCM — upsample to 16 kHz if needed, send as wav/pcm
            gladia_encoding = "wav/pcm"
            gladia_sample_rate = 16000
            gladia_bit_depth = 16

        headers = {
            "x-gladia-key": self.api_key,
            "Content-Type": "application/json",
        }

        session_config = {
            "encoding": gladia_encoding,
            "sample_rate": gladia_sample_rate,
            "bit_depth": gladia_bit_depth,
            "channels": 1,
            "model": self.model,
            "language_config": {"languages": ["en"]},
            "endpointing": 0.1,                          # fast utterance closing
            "maximum_duration_without_endpointing": 15,
            "messages_config": {
                "receive_partial_transcripts": True       # start processing early
            },
        }

        # Step 1 — create live session, get WS URL
        ws_url = None
        session_data = {}
        async with aiohttp.ClientSession() as http:
            try:
                async with http.post(_SESSION_URL, headers=headers, json=session_config) as resp:
                    if resp.status not in (200, 201):
                        body = await resp.text()
                        logger.error("[GladiaSTT] Session create failed %s: %s", resp.status, body[:300])
                        return
                    session_data = await resp.json()
                    ws_url = session_data.get("url")
                    session_id = session_data.get("id")
            except Exception as exc:
                logger.error("❌ [GladiaSTT] Session create error: %s", exc, exc_info=True)
                return

        if not ws_url:
            logger.error("[GladiaSTT] No WS URL in session response: %s", session_data)
            return
        logger.info("[GladiaSTT] Session %s — connecting (encoding=%s %dHz)", session_id, gladia_encoding, gladia_sample_rate)

        # Step 2 — stream audio over WebSocket
        async with aiohttp.ClientSession() as ws_http:
            try:
                async with ws_http.ws_connect(ws_url) as ws:
                    resample_state = None

                    async def _sender():
                        nonlocal resample_state
                        try:
                            async for chunk in audio_generator:
                                if not chunk or ws.closed:
                                    continue
                                if is_mulaw:
                                    # Send raw µ-law — no conversion, matches wav/ulaw session config
                                    await ws.send_bytes(chunk)
                                else:
                                    # Linear PCM — upsample to 16 kHz if source is 8 kHz
                                    pcm = chunk
                                    if sample_rate != 16000:
                                        pcm, resample_state = audioop.ratecv(
                                            pcm, 2, 1, sample_rate, 16000, resample_state
                                        )
                                    await ws.send_bytes(pcm)
                            if not ws.closed:
                                await ws.send_str(json.dumps({"type": "stop_recording"}))
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            logger.error("[GladiaSTT] Send error: %s", exc)

                    send_task = asyncio.create_task(_sender())
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                event_type = data.get("type", "")

                                if event_type == "transcript":
                                    inner = data.get("data", {})
                                    utterance = inner.get("utterance", {})
                                    text = (utterance.get("text") or "").strip()
                                    is_final = inner.get("is_final", False)
                                    if text:
                                        yield {"transcript": text, "is_final": is_final, "type": "transcript"}
                                elif event_type == "connected":
                                    logger.info("[GladiaSTT] Ready")
                                elif event_type in ("error", "warning"):
                                    logger.warning("[GladiaSTT] %s: %s", event_type, data)
                                elif event_type == "post_final_transcript":
                                    break
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.warning("[GladiaSTT] Server closed — code=%s reason=%r", msg.data, msg.extra)
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error("[GladiaSTT] WS error — code=%s reason=%r", msg.data, msg.extra)
                                break
                    finally:
                        send_task.cancel()

            except Exception as exc:
                logger.error("❌ [GladiaSTT] Streaming error: %s", exc, exc_info=True)
