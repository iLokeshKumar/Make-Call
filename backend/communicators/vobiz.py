import json
import logging
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class VobizCommunicator(TelephonyCommunicator):
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
                        "event": "playAudio",
                        "streamId": self.stream_sid,
                        "media": {
                            "contentType": "audio/x-mulaw",
                            "sampleRate": 8000,
                            "payload": b64_audio,
                        }
                    })
            except Exception as e:
                # Silently catch closed socket errors as normal hangups
                if "closed" in str(e).lower() or "close message has been sent" in str(e).lower():
                    logger.info("ℹ️ [Vobiz] Media send failed (Phone hung up)")
                else:
                    logger.error(f"❌ [Vobiz] Error sending media: {e}")
        else:
            logger.warning("⚠️ [Vobiz] Attempted to send media but stream_sid is missing!")

    async def clear_audio_buffer(self):
        if self.stream_sid:
            logger.info(f"🚫 [Vobiz] Clearing audio buffer for StreamSid: {self.stream_sid}")
            try:
                await self.websocket.send_json({
                    "event": "clearAudio",
                    "streamId": self.stream_sid
                })
            except Exception as e:
                logger.error(f"❌ [Vobiz] Error clearing buffer: {e}")
