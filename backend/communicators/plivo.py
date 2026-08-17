import json
import logging
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class PlivoCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = None

    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                yield data
        except Exception:
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str):
        try:
            # Robust check for open websocket
            if self.websocket.client_state.name == "CONNECTED":
                await self.websocket.send_json({
                    "event": "media",
                    "media": {"payload": b64_audio}
                })
        except Exception as e:
            # Silently catch closed socket errors as normal hangups
            if "closed" in str(e).lower() or "close message has been sent" in str(e).lower():
                logger.info("ℹ️ [Plivo] Media send failed (Phone hung up)")
            else:
                logger.error(f"❌ [Plivo] Error sending media: {e}")

    async def clear_audio_buffer(self):
        try:
            # Robust check for open websocket
            if self.websocket.client_state.name == "CONNECTED":
                logger.info("🚫 [Plivo] Clearing audio buffer")
                await self.websocket.send_json({
                    "event": "clear"
                })
        except Exception as e:
            # Silently catch closed socket/ASGI errors as normal hangups
            if any(x in str(e).lower() for x in ("closed", "close message", "websocket.close", "already completed")):
                logger.info("ℹ️ [Plivo] Clear buffer failed (Websocket already closed)")
            else:
                logger.error(f"❌ [Plivo] Error clearing buffer: {e}")