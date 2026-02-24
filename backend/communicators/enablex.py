import json
import logging
import base64
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class EnableXCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self._first_media = False

    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                try:
                    data = json.loads(message)
                    if "data" in data:
                        if not self._first_media:
                            logger.info(f"🎙️ [EnableX WS] Audio flow STARTED. Chunk size: {len(data['data'])}")
                            self._first_media = True
                        yield {"event": "media", "media": {"payload": data["data"]}}
                    elif data.get("event") == "stop" or data.get("state") == "disconnected":
                        yield {"event": "stop"}
                except json.JSONDecodeError:
                    # Fallback for unexpected non-JSON messages
                    yield {
                        "event": "media",
                        "media": {
                            "payload": base64.b64encode(message.encode()).decode() if isinstance(message, str) 
                                       else base64.b64encode(message).decode()
                        }
                    }
        except Exception as e:
            logger.error(f"❌ [EnableX WS] Receive Error: {e}")
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str):
        payload = {"event": "media", "data": b64_audio}
        try:
            await self.websocket.send_json(payload)
        except Exception as e:
            logger.error(f"❌ [EnableX] Error sending media: {e}")

    async def clear_audio_buffer(self):
        payload = {"event": "clear"}
        try:
            await self.websocket.send_json(payload)
            logger.info("🚫 [EnableX] Buffer cleared.")
        except Exception as e:
            logger.error(f"❌ [EnableX] Error clearing buffer: {e}")
