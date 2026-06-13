import asyncio
import json
import logging
import audioop
from typing import AsyncGenerator, Dict, Any
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)

# AssemblyAI real-time streaming STT — v3 API
# Docs: https://www.assemblyai.com/docs/speech-to-text/streaming
# URL:  wss://streaming.assemblyai.com/v3/ws?speech_model=...&sample_rate=...
# Auth: Authorization header (bare key, no "Bearer")
# Audio: 16kHz 16-bit mono PCM, raw binary frames
# Constraints: each frame must be 50–1000 ms (3200–32000 bytes at 16kHz 16-bit)
# Message types (server→client): Begin, Turn, Termination
# Terminate: send {"type": "Terminate"} to end session

_WS_BASE = "wss://streaming.assemblyai.com/v3/ws"
_MIN_FRAME_BYTES = 3200   # 50 ms × 16000 Hz × 2 bytes/sample
_MAX_FRAME_BYTES = 32000  # 1000 ms × 16000 Hz × 2 bytes/sample


class AssemblyAISTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "AssemblyAI"
        self.model = model or "u3-rt-pro"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("AssemblyAISTT initialized without API key — transcription will fail.")

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "pcm_mulaw",
        sample_rate: int = 8000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [AssemblyAISTT] API key missing.")
            yield {"transcript": "[Error: AssemblyAI API Key Missing]", "is_final": True}
            return

        out_rate = 16000
        params = urlencode({"speech_model": self.model, "sample_rate": out_rate})
        url = f"{_WS_BASE}?{params}"
        headers = {"Authorization": self.api_key}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(url, headers=headers) as ws:
                    # First message must be Begin — auth/param failures close immediately
                    init = await ws.receive()
                    if init.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(init.data)
                        if data.get("type") != "Begin":
                            logger.error("[AssemblyAISTT] Unexpected init message: %s", data)
                            return
                        logger.info("[AssemblyAISTT] Session %s started", data.get("id"))
                    elif init.type == aiohttp.WSMsgType.CLOSED:
                        logger.error(
                            "[AssemblyAISTT] Server closed before Begin — code=%s reason=%r "
                            "(1008=auth, 3006=bad format, 3007=timing/frame-size)",
                            init.data, init.extra,
                        )
                        return
                    else:
                        logger.error(
                            "[AssemblyAISTT] Bad init msg type=%s data=%r", init.type, init.data
                        )
                        return

                    is_mulaw = "mulaw" in encoding
                    resample_state = None

                    async def _sender():
                        nonlocal resample_state
                        # Buffer small chunks — AssemblyAI requires ≥50 ms per frame
                        buf = b""
                        try:
                            async for chunk in audio_generator:
                                if not chunk:
                                    continue
                                if ws.closed:
                                    break
                                pcm = audioop.ulaw2lin(chunk, 2) if is_mulaw else chunk
                                if sample_rate != out_rate:
                                    pcm, resample_state = audioop.ratecv(
                                        pcm, 2, 1, sample_rate, out_rate, resample_state
                                    )
                                buf += pcm
                                # Flush in max-frame-sized chunks once buffer is large enough
                                while len(buf) >= _MIN_FRAME_BYTES:
                                    frame, buf = buf[:_MAX_FRAME_BYTES], buf[_MAX_FRAME_BYTES:]
                                    if not ws.closed:
                                        await ws.send_bytes(frame)

                            # Flush remaining audio if it meets the minimum
                            if buf and len(buf) >= _MIN_FRAME_BYTES and not ws.closed:
                                await ws.send_bytes(buf)

                            if not ws.closed:
                                await ws.send_str(json.dumps({"type": "Terminate"}))
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _m = str(exc).lower()
                            if "closing" in _m or "closed" in _m:
                                logger.debug("[AssemblyAISTT] WS closed during send — expected at call end")
                            else:
                                logger.error("[AssemblyAISTT] Send error: %s", exc)

                    send_task = asyncio.create_task(_sender())
                    try:
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                data = json.loads(msg.data)
                                msg_type = data.get("type", "")

                                if msg_type == "Turn":
                                    text = (data.get("transcript") or "").strip()
                                    is_final = bool(data.get("end_of_turn"))
                                    if text:
                                        yield {
                                            "transcript": text,
                                            "is_final": is_final,
                                            "type": "transcript",
                                        }
                                elif msg_type == "Termination":
                                    logger.info(
                                        "[AssemblyAISTT] Session ended — audio=%.1fs session=%.1fs",
                                        data.get("audio_duration_seconds", 0),
                                        data.get("session_duration_seconds", 0),
                                    )
                                    break
                                elif msg_type not in ("Begin",):
                                    logger.debug("[AssemblyAISTT] msg=%s", data)
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                logger.warning(
                                    "[AssemblyAISTT] Server closed — code=%s reason=%r "
                                    "(1008=auth, 3006=bad format, 3007=timing/frame-size)",
                                    msg.data, msg.extra,
                                )
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(
                                    "[AssemblyAISTT] WS error — code=%s reason=%r",
                                    msg.data, msg.extra,
                                )
                                break
                    finally:
                        send_task.cancel()

            except Exception as exc:
                logger.error("❌ [AssemblyAISTT] Connection error: %s", exc, exc_info=True)
