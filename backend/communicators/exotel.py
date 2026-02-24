import json
import logging
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class ExotelCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = None

    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                try:
                    data = json.loads(message)
                    if data.get("event") != "media":
                        logger.debug(f"⏬ [Exotel WS] Received: {message[:200]}")
                    yield data
                except json.JSONDecodeError:
                    logger.error(f"❌ [Exotel WS] Received non-JSON message: {message[:100]}")
        except Exception as e:
            logger.error(f"❌ [Exotel WS] Receive Error: {e}")
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str):
        payload = {
            "event": "media",
            "media": {
                "payload": b64_audio
            }
        }
        try:
            await self.websocket.send_json(payload)
        except Exception as e:
            logger.error(f"❌ [Exotel] Error sending media: {e}")

    async def clear_audio_buffer(self):
        payload = {"event": "clear"}
        try:
            await self.websocket.send_json(payload)
            logger.info("🚫 [Exotel] Buffer cleared.")
        except Exception as e:
            logger.error(f"❌ [Exotel] Error clearing buffer: {e}")
