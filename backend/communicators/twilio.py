import json
import logging
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class TwilioCommunicator(TelephonyCommunicator):
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
        if self.stream_sid:
            try:
                # Robust check for open websocket
                if self.websocket.client_state.name == "CONNECTED":
                    await self.websocket.send_json({
                        "event": "media",
                        "streamSid": self.stream_sid,
                        "media": {"payload": b64_audio}
                    })
            except Exception as e:
                # Silently catch closed socket errors
                if "close message has been sent" not in str(e):
                    logger.error(f"❌ [Twilio] Error sending media: {e}")
        else:
            logger.warning("⚠️ [Twilio] Attempted to send media but stream_sid is missing!")

    async def clear_audio_buffer(self):
        if self.stream_sid:
            logger.info(f"🚫 [Twilio] Clearing audio buffer for StreamSid: {self.stream_sid}")
            try:
                await self.websocket.send_json({
                    "event": "clear",
                    "streamSid": self.stream_sid
                })
            except Exception as e:
                logger.error(f"❌ [Twilio] Error clearing buffer: {e}")
