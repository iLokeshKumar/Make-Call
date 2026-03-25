import base64
import logging
import time
import aiohttp
from credentials_service import get_credential

logger = logging.getLogger(__name__)


class ElevenLabsTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "ElevenLabs"

        db_model = get_credential("ELEVENLABS_TTS_MODEL")
        if model and ("eleven_" in model or "multilingual" in model):
            self.model = model
        else:
            self.model = db_model or "eleven_turbo_v2_5"

        self.api_key = api_key
        self.voice_id = voice_id or get_credential("ELEVENLABS_VOICE_ID") or "CwhOLp6mAE7h9asvUURR"
        self.last_latency = 0

        if not self.api_key:
            logger.warning("ElevenLabsTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [ElevenLabsTTS] API Key missing!")
            return

        start_time = time.time()
        # REST endpoint — ulaw_8000 is natively supported by ElevenLabs
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        params = {"output_format": "ulaw_8000"}
        payload = {"text": text, "model_id": self.model}

        session = aiohttp_session or aiohttp.ClientSession()
        should_close = aiohttp_session is None
        try:
            async with session.post(url, json=payload, params=params, headers=headers) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"❌ [ElevenLabsTTS] API Error {resp.status}: {error}")
                    return
                audio_bytes = await resp.read()
                first_byte_time = time.time() - start_time
                await communicator.send_media(base64.b64encode(audio_bytes).decode())
                self.last_latency = first_byte_time
                logger.info(f"🔊 [ElevenLabsTTS] Done. Latency: {first_byte_time:.3f}s | Bytes: {len(audio_bytes)}")
        except Exception as e:
            logger.error(f"❌ [ElevenLabsTTS] Error: {e}")
        finally:
            if should_close:
                await session.close()
