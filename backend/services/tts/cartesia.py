import json
import base64
import logging
import time
import aiohttp
import audioop
from utils.config import CARTESIA_API_KEY, CARTESIA_VOICE_ID

logger = logging.getLogger(__name__)

class CartesiaTTS:
    def __init__(self):
        self.provider = "Cartesia"
        self.model = "sonic-3"
        self.last_latency = 0

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None, **kwargs):
        try:
            start_time = time.time()
            first_byte_time = 0
            ctx = context_id or f"ctx_{int(time.time()*1000)}"

            payload = {
                "model_id": self.model,
                "transcript": text,
                "voice": {"mode": "id", "id": CARTESIA_VOICE_ID},
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": 16000,
                },
                "language": "en",
                "context_id": ctx,
            }

            async def _stream_on_ws(ws):
                nonlocal first_byte_time
                resample_state = None
                await ws.send_json(payload)

                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        if data.get("context_id") and data["context_id"] != ctx:
                            continue

                        audio_b64 = data.get("audio") or data.get("data")
                        if audio_b64:
                            if first_byte_time == 0:
                                first_byte_time = time.time() - start_time
                            pcm_16k = base64.b64decode(audio_b64)
                            pcm_8k, resample_state = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, resample_state)
                            mulaw = audioop.lin2ulaw(pcm_8k, 2)
                            await communicator.send_media(base64.b64encode(mulaw).decode())

                        if data.get("done"):
                            break
                    elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                        break

            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}&cartesia_version=2025-04-16"
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        await _stream_on_ws(ws)

            self.last_latency = first_byte_time
            logger.info(f"✅ [CartesiaTTS] Complete. First byte: {first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [CartesiaTTS] Error: {e}")
