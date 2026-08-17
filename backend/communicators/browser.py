import base64
import json
import logging
import audioop

from .base import TelephonyCommunicator

logger = logging.getLogger(__name__)


class BrowserCommunicator(TelephonyCommunicator):
    """Browser WebSocket adapter using JSON + base64 audio frames.

    Input audio is PCM s16le at 16kHz. Output audio is PCM s16le at 16kHz;
    the voice pipeline's TTS adapters may provide telephony PCM, so clients
    should treat the payload as signed PCM and resample if needed.
    """
    def __init__(self, websocket):
        self.websocket = websocket
        self.stream_sid = "browser"

    async def receive(self):
        try:
            async for raw in self.websocket.iter_text():
                data = json.loads(raw)
                if data.get("type") == "audio":
                    yield {"event": "media", "media": {"payload": data.get("audio", "")}}
                elif data.get("type") == "stop":
                    yield {"event": "stop"}
                elif data.get("type") == "start":
                    yield {"event": "start", "start": {"streamSid": "browser", "customParameters": data.get("parameters", {})}}
        except Exception as exc:
            logger.info("[Browser] websocket closed: %s", exc)
            yield {"event": "stop"}

    async def send_media(self, b64_audio: str):
        if self.websocket.client_state.name == "CONNECTED":
            # VoicePipeline's telephony TTS path emits 8kHz μ-law. Convert to
            # browser-friendly 16kHz signed PCM before sending it over JSON.
            raw = base64.b64decode(b64_audio)
            pcm8 = audioop.ulaw2lin(raw, 2)
            pcm16, _ = audioop.ratecv(pcm8, 2, 1, 8000, 16000, None)
            await self.websocket.send_json({
                "type": "audio", "audio": base64.b64encode(pcm16).decode(),
                "encoding": "linear16", "sample_rate": 16000,
            })

    async def clear_audio_buffer(self):
        if self.websocket.client_state.name == "CONNECTED":
            await self.websocket.send_json({"type": "clear_audio"})
