import audioop
import base64
import json
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)


class SmallestTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Smallest"
        self.model = model or "lightning_v3.1_pro"
        self.api_key = api_key or os.getenv("SMALLEST_API_KEY")
        self.voice_id = voice_id or "meher"
        self.sample_rate = 24000
        self.last_latency = 0.0

        if not self.api_key:
            logger.warning("SmallestTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None, **kwargs):
        if not self.api_key:
            logger.error("❌ No API key available for SmallestTTS")
            return

        start_time = time.time()
        first_byte_time = 0.0
        ctx = context_id or f"ctx_{int(time.time() * 1000)}"

        ws_url = "wss://api.smallest.ai/waves/v1/tts/live"
        headers = {"Authorization": f"Bearer {self.api_key}"}

        payload = {
            "text": text,
            "voice_id": self.voice_id,
            "model": self.model,
            "sample_rate": self.sample_rate,
            "context_id": ctx,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(ws_url, headers=headers) as ws:
                    await ws.send_json(payload)
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            try:
                                data = json.loads(msg.data)
                            except json.JSONDecodeError as e:
                                logger.warning(f"⚠️ [SmallestTTS] Failed to parse message: {e}")
                                continue

                            status = data.get("status")
                            if status == "chunk":
                                if first_byte_time == 0.0:
                                    first_byte_time = time.time() - start_time
                                    self.last_latency = first_byte_time
                                audio_data = base64.b64decode(data["data"]["audio"])
                                mulaw = audioop.lin2ulaw(
                                    audioop.ratecv(audio_data, 2, 1, self.sample_rate, 8000, None)[0],
                                    2,
                                )
                                await communicator.send_media(base64.b64encode(mulaw).decode())
                            elif status == "complete":
                                logger.debug(f"✔️ [SmallestTTS] Stream complete for context {ctx}")
                                break
                            elif status == "error":
                                error_msg = data.get("message", "Unknown error")
                                logger.error(f"❌ [SmallestTTS] API error: {error_msg}")
                                break
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                            logger.warning("⚠️ [SmallestTTS] WebSocket closed unexpectedly")
                            break
        except aiohttp.ClientConnectionError as e:
            logger.error(f"❌ [SmallestTTS] WebSocket connection closed: {e}")
        except Exception as e:
            logger.error(f"❌ [SmallestTTS] Unexpected error: {e}")
