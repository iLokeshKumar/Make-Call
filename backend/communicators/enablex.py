import json
import logging
import base64
import time
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class EnableXCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = None   # will hold stream_id
        self.voice_id = None
        self._seq = 0

    async def receive(self):
        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                event = data.get("event")

                if event == "connected":
                    continue

                elif event == "start_media":
                    stream_id = data.get("stream_id") or data.get("start", {}).get("stream_id")
                    self.stream_sid = stream_id
                    self.voice_id = data.get("start", {}).get("voice_id")
                    # Normalize to Twilio shape for VoicePipeline compatibility
                    yield {"event": "start", "start": {"streamSid": stream_id}}

                elif event == "media":
                    payload = data.get("media", {}).get("payload")
                    if payload:
                        yield {"event": "media", "media": {"payload": payload}}

                elif event == "stop_media":
                    yield {"event": "stop"}
                    return

        except Exception as e:
            logger.error(f"❌ [EnableX WS] Receive Error: {e}")
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str):
        if not self.stream_sid:
            logger.warning("⚠️ [EnableX] stream_sid missing")
            return
        self._seq += 1
        payload = {
            "event": "media",
            "voice_id": self.voice_id,
            "stream_id": self.stream_sid,
            "media": {
                "seq": self._seq,
                "timestamp": int(time.time() * 1000),
                "format": {"encoding": "ulaw", "sample_rate": 8000, "channels": 1},
                "payload": b64_audio
            }
        }
        try:
            await self.websocket.send_json(payload)
        except Exception as e:
            # Treat connection closures as normal hangups
            if "closed" in str(e).lower() or "close message has been sent" in str(e).lower():
                logger.info("ℹ️ [EnableX] Media send failed (Phone hung up)")
            else:
                logger.error(f"❌ [EnableX] send_media error: {e}")

    async def clear_audio_buffer(self):
        payload = {
            "event": "clear_media",
            "stream_id": self.stream_sid,
            "voice_id": self.voice_id
        }
        try:
            await self.websocket.send_json(payload)
            logger.info("🚫 [EnableX] Buffer cleared.")
        except Exception as e:
            if "closed" in str(e).lower() or "close message has been sent" in str(e).lower():
                logger.info("ℹ️ [EnableX] Buffer clear skipped (Phone already hung up)")
            else:
                logger.error(f"❌ [EnableX] clear error: {e}")