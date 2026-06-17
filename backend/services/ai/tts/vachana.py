import asyncio
import audioop
import base64
import json
import logging
import time

import websockets

logger = logging.getLogger(__name__)

_WS_URL = "wss://api.vachana.ai/api/v1/tts"

_VOICE_MAP = {v.lower(): v for v in ["Karan", "Simran", "Nara", "Riya", "Viraj", "Raju"]}


class VachanaTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Vachana"
        self.model = model or "vachana-voice-v3"
        self.api_key = api_key
        self.voice_id = voice_id or "Karan"
        self.last_latency = 0

        if not self.api_key:
            logger.warning("VachanaTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None, is_final=True, **kwargs):
        if not self.api_key:
            logger.error("❌ [VachanaTTS] API Key missing.")
            return

        start_time = time.time()
        first_byte_time = 0

        voice = _VOICE_MAP.get(self.voice_id.lower(), "Karan")

        payload = json.dumps({
            "text": text,
            "voice": voice,
            "language": "IND-IN",
            "model": self.model,
            "audio_config": {
                "sample_rate": 16000,
                "encoding": "linear_pcm",
                "num_channels": 1,
                "sample_width": 2,
                "container": "raw",
            },
        })

        headers = {"x-api-key-id": self.api_key}

        try:
            logger.info("🔊 [VachanaTTS] Connecting: text=%r voice=%s", text, voice)
            async with websockets.connect(
                _WS_URL,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            ) as ws:
                await ws.send(payload)

                resample_state = None
                async for message in ws:
                    if isinstance(message, bytes):
                        pcm_16k = message
                    else:
                        try:
                            data = json.loads(message)
                        except (json.JSONDecodeError, TypeError):
                            continue

                        msg_type = data.get("type")
                        if msg_type == "audio":
                            audio_b64 = (data.get("data") or {}).get("audio", "")
                            if not audio_b64:
                                continue
                            pcm_16k = base64.b64decode(audio_b64)
                        elif msg_type == "complete":
                            audio_b64 = (data.get("data") or {}).get("audio", "")
                            if audio_b64:
                                pcm_16k = base64.b64decode(audio_b64)
                            else:
                                break
                        elif msg_type == "error":
                            logger.error("❌ [VachanaTTS] Server error: %s", data)
                            break
                        else:
                            continue

                    if first_byte_time == 0:
                        first_byte_time = time.time() - start_time

                    # Strip WAV header if present
                    if len(pcm_16k) > 44 and pcm_16k[:4] == b"RIFF":
                        pcm_16k = pcm_16k[44:]

                    # Resample 16kHz → 8kHz, convert to mulaw for Twilio
                    pcm_8k, resample_state = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, resample_state)
                    mulaw = audioop.lin2ulaw(pcm_8k, 2)
                    await communicator.send_media(base64.b64encode(mulaw).decode())

                    if isinstance(message, str) and data.get("type") == "complete":
                        break

            self.last_latency = first_byte_time
            logger.info("✅ [VachanaTTS] Complete. First byte: %.3fs", first_byte_time)
        except Exception as e:
            logger.error("❌ [VachanaTTS] Error: %s", e)
