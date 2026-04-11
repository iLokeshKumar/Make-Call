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
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error("❌ [MistralTTS] API error %s: %s", response.status, error_text)
                        return

                    # Mistral PCM stream is float32 LE @ 24kHz.
                    # Convert to int16 -> downsample 24k->8k -> mu-law for Twilio-compatible media.
                    float_residual = b""
                    resample_state = None
                    chunk_count = 0
                    in_bytes_total = 0
                    out_bytes_total = 0
                    first_conversion_logged = False

                    async for chunk in response.content.iter_chunked(4096):
                        if chunk:
                            if not first_byte_time:
                                first_byte_time = time.time() - start_time
                                self.last_latency = first_byte_time
                            float_residual += chunk
                            usable = (len(float_residual) // 4) * 4
                            if usable == 0:
                                continue

                            float_block = float_residual[:usable]
                            float_residual = float_residual[usable:]
                            in_bytes_total += len(float_block)

                            pcm_24k_s16 = self._f32le_to_s16le(float_block)
                            pcm_8k_s16, resample_state = audioop.ratecv(
                                pcm_24k_s16, 2, 1, 24000, 8000, resample_state
                            )
                            mulaw_8k = audioop.lin2ulaw(pcm_8k_s16, 2)
                            out_bytes_total += len(mulaw_8k)
                            chunk_count += 1

                            if not first_conversion_logged:
                                logger.debug(
                                    "[MistralTTS] conversion pipeline active: src=f32le@24k -> s16le@24k -> s16le@8k -> mulaw@8k"
                                )
                                first_conversion_logged = True

                            if chunk_count % 25 == 0:
                                logger.debug(
                                    "[MistralTTS] chunks=%d in=%dB float24k out=%dB mulaw8k",
                                    chunk_count,
                                    in_bytes_total,
                                    out_bytes_total,
                                )

                            await communicator.send_media(base64.b64encode(mulaw_8k).decode("utf-8"))

            logger.info(
                "✅ [MistralTTS] Complete. First byte: %.3fs | chunks=%d | in=%dB float24k | out=%dB mulaw8k",
                first_byte_time,
                chunk_count,
                in_bytes_total,
                out_bytes_total,
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
