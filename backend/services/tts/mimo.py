import audioop
import base64
import logging
import time
import aiohttp

logger = logging.getLogger(__name__)

# Default PCM sample rate Mimo TTS outputs (matches OpenAI TTS convention)
MIMO_TTS_SAMPLE_RATE = 24000


class MimoTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Mimo"
        self.model = model or "mimo-v2-tts"
        self.api_key = api_key
        # voice_id here is a text description of the desired voice, e.g.
        # "Professional female, calm, clear, neutral accent"
        self.voice_id = voice_id or "Professional female voice, calm and clear"
        self.last_latency = 0

        if not self.api_key:
            logger.warning("MimoTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [MimoTTS] API Key missing!")
            return

        start_time = time.time()
        # OpenAI-compatible audio/speech endpoint
        url = "https://api.xiaomimimo.com/v1/audio/speech"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": text,
            "voice": self.voice_id,
            "response_format": "pcm",  # raw PCM at MIMO_TTS_SAMPLE_RATE Hz
        }

        session = aiohttp_session or aiohttp.ClientSession()
        should_close = aiohttp_session is None
        try:
            async with session.post(url, json=payload, headers=headers) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"❌ [MimoTTS] API Error {resp.status}: {error}")
                    return

                pcm_bytes = await resp.read()
                first_byte_time = time.time() - start_time

                # Convert PCM 24kHz → mulaw 8kHz for telephony
                pcm_8k, _ = audioop.ratecv(pcm_bytes, 2, 1, MIMO_TTS_SAMPLE_RATE, 8000, None)
                mulaw = audioop.lin2ulaw(pcm_8k, 2)

                await communicator.send_media(base64.b64encode(mulaw).decode())
                self.last_latency = first_byte_time
                logger.info(
                    f"🔊 [MimoTTS] Done. Latency: {first_byte_time:.3f}s | "
                    f"PCM: {len(pcm_bytes)}B → mulaw: {len(mulaw)}B"
                )
        except Exception as e:
            logger.error(f"❌ [MimoTTS] Error: {e}")
        finally:
            if should_close:
                await session.close()
