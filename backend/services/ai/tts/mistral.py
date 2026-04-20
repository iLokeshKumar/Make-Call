import base64
import json
import logging
import os
import struct
import time
import aiohttp
import audioop
from typing import Optional

logger = logging.getLogger(__name__)

class MistralTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Mistral"
        self.model = model or "mistral-tts"
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        self.voice_id = voice_id or "gb_jane_confident"  # Default voice/model for Mistral
        self.last_latency = 0

        if not self.api_key:
            logger.warning("MistralTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None, **kwargs):
        """Generate speech using Mistral's TTS API and stream audio to communicator."""
        if not self.api_key:
            logger.error("❌ No API key available for MistralTTS")
            return

        try:
            start_time = time.time()
            first_byte_time = 0

            url = "https://api.mistral.ai/v1/audio/speech"
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "input": text,
                "voice_id": self.voice_id,
                "stream": True,
                "response_format": "pcm",
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    # DIAGNOSTIC: log status + content-type even on success so we
                    # can verify Mistral is really returning a float32 PCM stream.
                    logger.info(
                        "🔍 [MistralTTS] status=%s content-type=%s transfer-encoding=%s",
                        response.status,
                        response.headers.get("Content-Type", "<none>"),
                        response.headers.get("Transfer-Encoding", "<none>"),
                    )
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error("❌ [MistralTTS] API error %s: %s", response.status, error_text)
                        return

                    # Mistral TTS streams Server-Sent Events. Each `speech.audio.delta`
                    # event carries a JSON payload whose `audio` field is base64-encoded
                    # f32le PCM @ 24kHz. Decode → s16 → downsample to 8k → µ-law for Twilio.
                    sse_buffer = ""
                    float_residual = b""   # carries partial float samples across deltas
                    resample_state = None
                    chunk_count = 0
                    in_bytes_total = 0
                    out_bytes_total = 0
                    first_audio_logged = False
                    # Per-call diagnostics — temporary, remove once the parser is proven.
                    sse_events_total = 0
                    sse_event_types_seen: dict = {}
                    first_event_logged = False

                    async def process_audio_bytes(raw_audio: bytes):
                        """Convert one block of f32le@24k PCM bytes into µ-law@8k and send."""
                        nonlocal float_residual, resample_state, chunk_count
                        nonlocal in_bytes_total, out_bytes_total, first_audio_logged

                        if not raw_audio:
                            return
                        float_residual += raw_audio
                        usable = (len(float_residual) // 4) * 4
                        if usable == 0:
                            return

                        float_block = float_residual[:usable]
                        float_residual = float_residual[usable:]
                        in_bytes_total += len(float_block)

                        if not first_audio_logged:
                            head = float_block[:64]
                            logger.info(
                                "🔍 [MistralTTS] first_audio_block_len=%d first64_hex=%s",
                                len(float_block),
                                head.hex(),
                            )
                            first_audio_logged = True

                        pcm_24k_s16 = self._f32le_to_s16le(float_block)
                        pcm_8k_s16, resample_state = audioop.ratecv(
                            pcm_24k_s16, 2, 1, 24000, 8000, resample_state
                        )
                        mulaw_8k = audioop.lin2ulaw(pcm_8k_s16, 2)
                        out_bytes_total += len(mulaw_8k)
                        chunk_count += 1
                        await communicator.send_media(base64.b64encode(mulaw_8k).decode("utf-8"))

                    async for chunk in response.content.iter_chunked(4096):
                        if not chunk:
                            continue
                        if not first_byte_time:
                            first_byte_time = time.time() - start_time
                            self.last_latency = first_byte_time

                        sse_buffer += chunk.decode("utf-8", errors="replace")

                        # SSE events are separated by a blank line (\n\n or \r\n\r\n).
                        while True:
                            sep_idx = -1
                            for sep in ("\n\n", "\r\n\r\n"):
                                idx = sse_buffer.find(sep)
                                if idx != -1 and (sep_idx == -1 or idx < sep_idx):
                                    sep_idx = idx
                                    sep_len = len(sep)
                            if sep_idx == -1:
                                break

                            event_block = sse_buffer[:sep_idx]
                            sse_buffer = sse_buffer[sep_idx + sep_len:]

                            event_type = None
                            data_payload = None
                            for line in event_block.splitlines():
                                if line.startswith("event:"):
                                    event_type = line[6:].strip()
                                elif line.startswith("data:"):
                                    piece = line[5:].lstrip()
                                    data_payload = piece if data_payload is None else data_payload + piece

                            sse_events_total += 1
                            sse_event_types_seen[event_type or "<no-event>"] = (
                                sse_event_types_seen.get(event_type or "<no-event>", 0) + 1
                            )

                            # DIAGNOSTIC: dump the full first event so we can see the real shape.
                            if not first_event_logged:
                                logger.info(
                                    "🔍 [MistralTTS] first_event event_type=%r data_len=%d data_head=%r",
                                    event_type,
                                    len(data_payload) if data_payload else 0,
                                    (data_payload or "")[:200],
                                )
                                first_event_logged = True

                            if event_type != "speech.audio.delta" or not data_payload:
                                continue

                            try:
                                payload = json.loads(data_payload)
                            except json.JSONDecodeError as e:
                                logger.warning(
                                    "⚠️ [MistralTTS] Bad JSON in SSE data: %s | head=%r",
                                    e, (data_payload or "")[:120],
                                )
                                continue

                            if isinstance(payload, dict):
                                audio_b64 = (
                                    payload.get("audio_data")
                                    or payload.get("audio")
                                    or payload.get("delta")
                                    or payload.get("data")
                                )
                            else:
                                audio_b64 = None

                            if not audio_b64:
                                logger.info(
                                    "🔍 [MistralTTS] delta event but no audio field; keys=%s",
                                    list(payload.keys()) if isinstance(payload, dict) else type(payload).__name__,
                                )
                                continue

                            try:
                                raw_audio = base64.b64decode(audio_b64)
                            except Exception as e:
                                logger.warning("⚠️ [MistralTTS] Bad base64 in SSE audio: %s", e)
                                continue

                            await process_audio_bytes(raw_audio)

            logger.info(
                "✅ [MistralTTS] Complete. First byte: %.3fs | chunks=%d | in=%dB float24k | out=%dB mulaw8k",
                first_byte_time,
                chunk_count,
                in_bytes_total,
                out_bytes_total,
            )
            logger.info(
                "🔍 [MistralTTS] SSE summary: total_events=%d types=%s sse_buffer_leftover=%d chars",
                sse_events_total,
                sse_event_types_seen,
                len(sse_buffer),
            )
            if sse_events_total == 0 and sse_buffer:
                # No events got split out, but data arrived. Show what's sitting in the buffer.
                logger.info(
                    "🔍 [MistralTTS] sse_buffer head=%r",
                    sse_buffer[:400],
                )
        except aiohttp.ClientError as e:
            logger.error("❌ [MistralTTS] HTTP error: %s", e)
        except Exception as e:
            logger.error("❌ [MistralTTS] Unexpected error: %s", e)

    @staticmethod
    def _f32le_to_s16le(float_bytes: bytes) -> bytes:
        out = bytearray()
        for (sample,) in struct.iter_unpack("<f", float_bytes):
            if sample > 1.0:
                sample = 1.0
            elif sample < -1.0:
                sample = -1.0
            out.extend(struct.pack("<h", int(sample * 32767.0)))
        return bytes(out)

    async def get_voices(self) -> list:
        """Get available voices from Mistral (placeholder - implement if API supports)."""
        # Mistral may not have a voices endpoint, so return known voices
        return [
            {"id": "mistral-7b-instruct", "name": "Mistral 7B", "language": "en"},
            # Add more voices as they become available
        ]
