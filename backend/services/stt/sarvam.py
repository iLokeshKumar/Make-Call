import audioop
import io
import json
import logging
import struct
import wave
import aiohttp
from typing import AsyncGenerator, Dict, Any
from utils import settings_cache

logger = logging.getLogger(__name__)

# The WS STT endpoint expects audio at 16kHz (minimum supported for real-time)
_STT_AUDIO_RATE = 16000
# Frame size = 20ms @ 16kHz, 2 bytes/sample = 640 bytes
_FRAME_SIZE = 640


def _build_wav_frame(pcm_16k: bytes) -> bytes:
    """Wrap raw 16kHz s16le PCM into a valid WAV byte blob."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_STT_AUDIO_RATE)
        wf.writeframes(pcm_16k)
    return buf.getvalue()


class SarvamSTT:
    """
    Sarvam STT using the REST API endpoint.
    Endpoint: https://api.sarvam.ai/speech-to-text

    Note: This is a REVERSION from the WebSocket implementation due to reliability issues.
    Latency will be higher as it processes audio via discrete HTTP POST requests.
    """
    REST_URL = "https://api.sarvam.ai/speech-to-text"

    def __init__(self, api_key: str = None, language: str = "en-IN", model: str = None):
        self.provider = "Sarvam"
        self.model = model or settings_cache.get("SARVAM_STT_MODEL") or "saaras:v3"
        self.language = language
        self.api_key = api_key

        if not self.api_key:
            logger.warning("SarvamSTT initialized without an API key! Transcription will fail.")

    async def transcribe(
        self, audio_generator, encoding: str = "pcm_mulaw", sample_rate: int = 8000
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [SarvamSTT] API Key missing.")
            yield {"transcript": "[Error: Sarvam API Key Missing]", "is_final": True}
            return

        headers = {"api-subscription-key": self.api_key}
        
        # We need to accumulate some audio to make a viable REST request
        # or send smaller chunks. For voice latency, we'll try sending ~1-2 seconds of audio.
        buffer = b""
        chunk_threshold = 32000 # ~2 seconds of 16k PCM (640 bytes per 20ms frame * 100)
        
        resample_state = None

        async with aiohttp.ClientSession() as session:
            try:
                async for raw_chunk in audio_generator:
                    if not raw_chunk:
                        continue

                    # Convert to linear16
                    if "mulaw" in encoding:
                        pcm = audioop.ulaw2lin(raw_chunk, 2)
                    else:
                        pcm = raw_chunk

                    # Upsample from source rate → 16kHz
                    if sample_rate != _STT_AUDIO_RATE:
                        pcm, resample_state = audioop.ratecv(
                            pcm, 2, 1, sample_rate, _STT_AUDIO_RATE, resample_state
                        )
                    
                    buffer += pcm
                    
                    if len(buffer) >= chunk_threshold:
                        # Wrap buffer in WAV and send
                        wav_data = _build_wav_frame(buffer)
                        buffer = b"" # Reset buffer
                        
                        # Prepare multipart data
                        data = aiohttp.FormData()
                        data.add_field('file', wav_data, filename='audio.wav', content_type='audio/wav')
                        data.add_field('model', self.model)
                        data.add_field('language_code', self.language)
                        
                        logger.debug(f"📤 [SarvamSTT REST] Sending chunk ({len(wav_data)} bytes)...")
                        async with session.post(self.REST_URL, headers=headers, data=data) as resp:
                            if resp.status == 200:
                                res_json = await resp.json()
                                transcript = res_json.get("transcript", "").strip()
                                if transcript:
                                    logger.info(f"🎙️ [SarvamSTT REST] Transcript: '{transcript}'")
                                    yield {
                                        "transcript": transcript,
                                        "is_final": True,
                                        "type": "transcript",
                                    }
                            else:
                                text = await resp.text()
                                logger.error(f"❌ [SarvamSTT REST] Error {resp.status}: {text}")

            except Exception as e:
                logger.error(f"❌ [SarvamSTT REST] Transcription loop error: {e}")
