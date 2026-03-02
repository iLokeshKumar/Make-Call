import json
import base64
import logging
from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)

class ExotelCommunicator(TelephonyCommunicator):
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = None

    async def receive(self):
        """
        Exotel sends: connected → start → media... → stop
        stream_sid lives at data["stream_sid"], not data["start"]["streamSid"]
        """
        try:
            async for message in self.websocket.iter_text():
                data = json.loads(message)
                event = data.get("event")

                # Normalize to Twilio-compatible shape so VoicePipeline works unchanged
                if event == "connected":
                    continue  # skip, nothing useful here

                elif event == "start":
                    # Exotel puts stream_sid at root AND inside start{}
                    sid = data.get("stream_sid") or data.get("start", {}).get("stream_sid")
                    yield {
                        "event": "start",
                        "start": {"streamSid": sid}  # normalize to Twilio shape
                    }

                elif event == "media":
                    # Exotel audio is already raw PCM s16le — NOT mulaw
                    # Pass as-is, but tag it so STT knows encoding
                    yield {
                        "event": "media",
                        "media": {"payload": data["media"]["payload"]},
                        "encoding": "linear16"   # ← key difference from Twilio
                    }

                elif event == "stop":
                    yield {"event": "stop"}
                    return

                elif event == "dtmf":
                    yield data  # pass through if you want to handle keypresses later

        except Exception:
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str):
        """
        Exotel expects raw PCM s16le base64 back — NOT mulaw.
        b64_audio coming from TTS must be PCM, not mulaw.
        """
        if self.stream_sid:
            try:
                if self.websocket.client_state.name == "CONNECTED":
                    await self.websocket.send_json({
                        "event": "media",
                        "stream_sid": self.stream_sid,   # Exotel uses stream_sid not streamSid
                        "media": {"payload": b64_audio}
                    })
            except Exception as e:
                if "close message has been sent" not in str(e):
                    logger.error(f"❌ [Exotel] send_media error: {e}")
        else:
            logger.warning("⚠️ [Exotel] stream_sid missing, cannot send media")

    async def clear_audio_buffer(self):
        if self.stream_sid:
            try:
                await self.websocket.send_json({
                    "event": "clear",
                    "stream_sid": self.stream_sid
                })
                logger.info(f"🚫 [Exotel] Buffer cleared")
            except Exception as e:
                logger.error(f"❌ [Exotel] clear error: {e}")