import base64
import logging
import time
import aiohttp
from utils.config import SARVAM_API_KEY

logger = logging.getLogger(__name__)

class SarvamTTS:
    def __init__(self):
        self.provider = "Sarvam"
        self.model = "bulbul:v3"
        self.last_latency = 0

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not SARVAM_API_KEY:
            logger.error("❌ [SarvamTTS] API Key missing!")
            return

        start_time = time.time()
        first_byte_time = 0
        url = "https://api.sarvam.ai/text-to-speech/stream"
        headers = {
            "api-subscription-key": SARVAM_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "text": text,
            "target_language_code": "en-IN",
            "speaker": "ritu",
            "model": self.model,
            "pace": 1.1,
            "speech_sample_rate": 8000,
            "output_audio_codec": "mulaw",
            "enable_preprocessing": True
        }

        async def _stream_on_response(response):
            nonlocal first_byte_time
            async for chunk in response.content.iter_any():
                if chunk:
                    if first_byte_time == 0:
                        first_byte_time = time.time() - start_time
                    await communicator.send_media(base64.b64encode(chunk).decode("utf-8"))

        try:
            session = aiohttp_session if aiohttp_session else aiohttp.ClientSession()
            should_close = aiohttp_session is None
            try:
                async with session.post(url, headers=headers, json=payload) as response:
                    await _stream_on_response(response)
            finally:
                if should_close: await session.close()
            
            self.last_latency = first_byte_time
            logger.info(f"✅ [SarvamTTS] Complete. First byte: {first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [SarvamTTS] Error: {e}")
