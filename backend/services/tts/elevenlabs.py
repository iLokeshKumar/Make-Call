import json
import base64
import logging
import time
import aiohttp
import audioop
from utils.config import ELEVENLABS_VOICE_ID

logger = logging.getLogger(__name__)

class ElevenLabsTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "ElevenLabs"
        self.model = model or "eleven_turbo_v2_5"
        self.api_key = api_key
        self.voice_id = voice_id or ELEVENLABS_VOICE_ID
        self.last_latency = 0
        
        if not self.api_key:
            logger.warning("ElevenLabsTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [ElevenLabsTTS] API Key missing!")
            return

        start_time = time.time()
        first_byte_time = 0
        url = f"wss://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream-input?model_id={self.model}&output_format=pcm_16000"
        
        async def _stream_on_ws(ws):
            nonlocal first_byte_time
            resample_state = None
            await ws.send_json({
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "xi_api_key": self.api_key
            })
            await ws.send_json({"text": text, "try_trigger_generation": True})
            await ws.send_json({"text": ""})
            
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if data.get("audio"):
                        if first_byte_time == 0:
                            first_byte_time = time.time() - start_time
                        
                        pcm_16k = base64.b64decode(data["audio"])
                        pcm_8k, resample_state = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, resample_state)
                        ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                        await communicator.send_media(base64.b64encode(ulaw_8k).decode())
                    
                    if data.get("isFinal"):
                        break
                elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                    break

        headers = {"xi-api-key": self.api_key}
        try:
            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                session = aiohttp_session if aiohttp_session else aiohttp.ClientSession()
                should_close = aiohttp_session is None
                try:
                    async with session.ws_connect(url, headers=headers) as ws:
                        await _stream_on_ws(ws)
                finally:
                    if should_close: await session.close()
            
            self.last_latency = first_byte_time
            logger.info(f"🔊 [ElevenLabsTTS] Complete. First byte: {first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [ElevenLabsTTS] Error: {e}")
