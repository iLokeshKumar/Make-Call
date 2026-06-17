import asyncio
import audioop
import base64
import json
import logging
from typing import AsyncGenerator, Dict, Any

import aiohttp

logger = logging.getLogger(__name__)

# Inworld real-time streaming STT — bidirectional WebSocket
# Docs: https://docs.inworld.ai/api-reference/sttAPI/speechtotext/transcribe-stream-websocket
# URL:  wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional
# Auth: Authorization: Basic {api_key} header
# Flow:
#   1. Connect with Basic auth header
#   2. Send JSON: {"transcribeConfig": {"modelId": ..., "audioEncoding": "MULAW", "sampleRateHertz": 8000}}
#   3. Convert Twilio μ-law 8kHz → LINEAR16 16kHz, send JSON {"content": "<base64>"} per frame
#   4. Receive {"transcript": "...", "isFinal": true/false}
#   5. Send {"endTurn": {}} then {"closeStream": {}} when done

_WS_URL = "wss://api.inworld.ai/stt/v1/transcribe:streamBidirectional"


class InworldSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Inworld"
        self.model = model or "inworld/inworld-stt-1"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("InworldSTT initialized without API key — transcription will fail.")

    async def transcribe(
        self,
        audio_generator: AsyncGenerator[bytes, None],
        encoding: str = "pcm_mulaw",
        sample_rate: int = 8000,
        **_kwargs,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [InworldSTT] API key missing.")
            yield {"transcript": "[Error: Inworld API Key Missing]", "is_final": True}
            return

        headers = {"Authorization": f"Basic {self.api_key}"}

        async with aiohttp.ClientSession() as http:
            try:
                async with http.ws_connect(_WS_URL, headers=headers) as ws:
                    logger.info("[InworldSTT] Connected — model=%s", self.model)

                    # Step 1: send transcribe config — Inworld streaming requires LINEAR16 at 16kHz
                    config_payload = {
                        "transcribeConfig": {
                            "modelId": self.model,
                            "audioEncoding": "LINEAR16",
                            "sampleRateHertz": 16000,
                            "numberOfChannels": 1,
                            "language": "en-US",
                            "languageCode": "en-US",
                        }
                    }
                    await ws.send_json(config_payload)
                    logger.info("[InworldSTT] transcribeConfig sent: %s", json.dumps(config_payload))

                    chunks_sent = 0
                    last_transcript_time = [0.0]
                    _resample_state = None

                    async def _sender():
                        nonlocal chunks_sent, _resample_state
                        pcm_buffer = bytearray()
                        try:
                            async for chunk in audio_generator:
                                if not chunk or ws.closed:
                                    if not chunk:
                                        logger.warning("[InworldSTT] SEND: empty chunk — Twilio stream issue?")
                                    continue

                                mulaw_len = len(chunk)
                                # Step 1: mulaw → LINEAR16 8kHz (width=2 → 2 bytes/sample, size doubles)
                                lin16 = audioop.ulaw2lin(chunk, 2)
                                # Step 2: LINEAR16 8kHz → LINEAR16 16kHz (samples double, size doubles again)
                                pcm, _resample_state = audioop.ratecv(lin16, 2, 1, 8000, 16000, _resample_state)
                                pcm_buffer.extend(pcm)

                                # Send in 20ms (640 bytes) chunks to avoid Inworld minimum duration validation error
                                while len(pcm_buffer) >= 640:
                                    chunk_to_send = bytes(pcm_buffer[:640])
                                    pcm_buffer = pcm_buffer[640:]

                                    chunks_sent += 1
                                    b64_data = base64.b64encode(chunk_to_send).decode()
                                    if chunks_sent <= 10 or chunks_sent % 100 == 0:
                                        logger.info(
                                            "[InworldSTT] chunk #%d: len=%dB (20ms) | payload format: {'audioChunk': {'content': '%s...'}}",
                                            chunks_sent,
                                            len(chunk_to_send),
                                            b64_data[:20],
                                        )

                                    await ws.send_json({
                                        "audioChunk": {
                                            "content": b64_data
                                        }
                                    })

                            # Flush any remaining audio
                            if len(pcm_buffer) > 0:
                                # Pad to exactly 640 bytes (20ms) if shorter
                                if len(pcm_buffer) < 640:
                                    padding_len = 640 - len(pcm_buffer)
                                    logger.info("[InworldSTT] Padding final chunk: %dB → 640B with silence", len(pcm_buffer))
                                    pcm_buffer.extend(b'\x00' * padding_len)
                                
                                chunk_to_send = bytes(pcm_buffer)
                                chunks_sent += 1
                                b64_data = base64.b64encode(chunk_to_send).decode()
                                logger.info(
                                    "[InworldSTT] final chunk #%d: len=%dB (20ms) | payload format: {'audioChunk': {'content': '%s...'}}",
                                    chunks_sent,
                                    len(chunk_to_send),
                                    b64_data[:20],
                                )
                                await ws.send_json({
                                    "audioChunk": {
                                        "content": b64_data
                                    }
                                })

                            logger.info("[InworldSTT] SEND done — %d chunks sent total", chunks_sent)
                            if not ws.closed:
                                logger.info("[InworldSTT] SEND closeStream")
                                await ws.send_json({"closeStream": {}})
                        except asyncio.CancelledError:
                            raise
                        except Exception as exc:
                            _m = str(exc).lower()
                            if "closing" in _m or "closed" in _m:
                                logger.debug("[InworldSTT] WS closed during send — expected at call end")
                            else:
                                logger.error("[InworldSTT] Send error: %s", exc)

                    send_task = asyncio.create_task(_sender())
                    try:
                        import time as _time
                        speech_started_at = [0.0]
                        async for msg in ws:
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                logger.info("[InworldSTT] RAW recv: %s", msg.data)
                                try:
                                    data = json.loads(msg.data)
                                except json.JSONDecodeError as je:
                                    logger.error("[InworldSTT] JSON decode error: %s — raw=%r", je, msg.data)
                                    continue
                                if "result" in data:
                                    rdata = data["result"]
                                    if "speechStarted" in rdata:
                                        speech_started_at[0] = _time.time()
                                        logger.info("[InworldSTT] speechStarted event")
                                        yield {"type": "speech_started"}
                                    elif "speechStopped" in rdata:
                                        logger.info("[InworldSTT] speechStopped event")
                                        yield {"type": "speech_stopped"}
                                    elif "transcription" in rdata:
                                        trans = rdata["transcription"]
                                        transcript = (trans.get("transcript") or "").strip()
                                        is_final = bool(trans.get("isFinal", False))
                                        last_transcript_time[0] = _time.time()
                                        if transcript:
                                            lag = (last_transcript_time[0] - speech_started_at[0]) if speech_started_at[0] else 0
                                            logger.info(
                                                "[InworldSTT] transcript final=%s lag=%.2fs: %r",
                                                is_final, lag, transcript,
                                            )
                                            yield {
                                                "transcript": transcript,
                                                "is_final": is_final,
                                                "type": "transcript",
                                            }
                                    elif "usage" in rdata:
                                        logger.info("[InworldSTT] usage event: %s", rdata["usage"])
                                    else:
                                        logger.info("[InworldSTT] unhandled keys in result=%s: %s", list(rdata.keys()), msg.data[:300])
                                else:
                                    event_type = data.get("event")
                                    speech_started = data.get("speechStarted")
                                    speech_stopped = data.get("speechStopped")
                                    if event_type == "speechStarted" or speech_started:
                                        speech_started_at[0] = _time.time()
                                        logger.info("[InworldSTT] speechStarted event")
                                        yield {"type": "speech_started"}
                                    elif event_type == "speechStopped" or speech_stopped:
                                        logger.info("[InworldSTT] speechStopped event")
                                        yield {"type": "speech_stopped"}
                                    else:
                                        transcript = (data.get("transcript") or "").strip()
                                        is_final = bool(data.get("isFinal", False))
                                        last_transcript_time[0] = _time.time()
                                        if transcript:
                                            lag = (last_transcript_time[0] - speech_started_at[0]) if speech_started_at[0] else 0
                                            logger.info(
                                                "[InworldSTT] transcript final=%s lag=%.2fs: %r",
                                                is_final, lag, transcript,
                                            )
                                            yield {
                                                "transcript": transcript,
                                                "is_final": is_final,
                                                "type": "transcript",
                                            }
                                        else:
                                            logger.info("[InworldSTT] unhandled keys=%s: %s", list(data.keys()), msg.data[:300])
                            elif msg.type == aiohttp.WSMsgType.BINARY:
                                logger.warning("[InworldSTT] unexpected binary frame len=%d", len(msg.data))
                            elif msg.type == aiohttp.WSMsgType.CLOSED:
                                if not last_transcript_time[0] and chunks_sent > 20:
                                    logger.warning(
                                        "[InworldSTT] stream closed with NO transcript after %d chunks — likely encoding/format mismatch",
                                        chunks_sent,
                                    )
                                logger.info(
                                    "[InworldSTT] Session closed — code=%s reason=%r",
                                    msg.data, msg.extra,
                                )
                                break
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(
                                    "[InworldSTT] WS error — code=%s reason=%r",
                                    msg.data, msg.extra,
                                )
                                break
                    finally:
                        send_task.cancel()

            except Exception as exc:
                logger.error("❌ [InworldSTT] Connection error: %s", exc, exc_info=True)