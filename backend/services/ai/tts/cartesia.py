import json
import base64
import logging
import time
import aiohttp
import audioop
from utils import settings_cache

logger = logging.getLogger(__name__)

class CartesiaTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Cartesia"
        self.model = model or "sonic-3.5"
        self.api_key = api_key
        self.voice_id = voice_id or "694f9369-aef9-5dba-99c5-6c1d27e44b9a"
        self.last_latency = 0
        
        if not self.api_key:
            logger.warning("CartesiaTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None, is_final=True, **kwargs):
        try:
            start_time = time.time()
            first_byte_time = 0
            ctx = context_id or f"ctx_{int(time.time()*1000)}"

            payload = {
                "model_id": self.model,
                "transcript": text,
                "voice": {"mode": "id", "id": self.voice_id},
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_s16le",
                    "sample_rate": 16000,
                },
                "language": "en",
                "context_id": ctx,
                "continue": not is_final, # Cartesia-specific: don't close context yet if not final
            }

            async def _stream_on_ws(ws):
                nonlocal first_byte_time
                resample_state = None
                await ws.send_json(payload)

                # Only listen for audio if we sent a chunk. 
                # If we are just streaming in, we might want to listen in a separate loop.
                # For now, we'll listen until this chunk's audio is mostly done or context closes.
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

                        if data.get("done") or (is_final and data.get("type") == "done"):
                            break
                    elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                        break

            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                url = f"wss://api.cartesia.ai/tts/websocket?api_key={self.api_key}&cartesia_version=2026-05-04"
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        await _stream_on_ws(ws)

            self.last_latency = first_byte_time
            logger.info(f"✅ [CartesiaTTS] Complete. First byte: {first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [CartesiaTTS] Error: {e}")
