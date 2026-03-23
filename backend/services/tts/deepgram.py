import json
import base64
import logging
import time
import aiohttp
from credentials_service import get_credential

logger = logging.getLogger(__name__)

class DeepgramTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Deepgram"
        self.model = model or voice_id or get_credential("DEEPGRAM_VOICE") or "aura-asteria-en"
        self.api_key = api_key
        self.last_latency = 0
        
        if not self.api_key:
            logger.warning("DeepgramTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [DeepgramTTS] API Key missing!")
            return

        start_time = time.time()
        first_byte_time = 0
        url = f"wss://api.deepgram.com/v1/speak?model={self.model}&encoding=mulaw&sample_rate=8000"
        headers = {"Authorization": f"Token {self.api_key}"}
        
        async def _stream_on_ws(ws):
            nonlocal first_byte_time
            await ws.send_json({"type": "Speak", "text": text})
            await ws.send_json({"type": "Flush"})
            
            async for message in ws:
                if message.type == aiohttp.WSMsgType.BINARY:
                    if first_byte_time == 0:
                        first_byte_time = time.time() - start_time
                    await communicator.send_media(base64.b64encode(message.data).decode("utf-8"))
                elif message.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if data.get("type") == "Flushed":
                        break
                elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                    break

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
            logger.info(f"✅ [DeepgramTTS] Complete. First byte: {first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [DeepgramTTS] Error: {e}")
