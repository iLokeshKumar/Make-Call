import asyncio
import audioop
import base64
import io
import logging
import os
import time
import wave

from groq import Groq

logger = logging.getLogger(__name__)

# Twilio media streams expect 8kHz mono µ-law.
TWILIO_SAMPLE_RATE = 8000


class GroqTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Groq"
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model or os.getenv("GROQ_TTS_MODEL") or "canopylabs/orpheus-v1-english"
        self.voice_id = voice_id or os.getenv("GROQ_VOICE") or "troy"
        self.client = Groq(api_key=self.api_key) if self.api_key else None
        self.last_latency = 0.0

        if not self.api_key:
            logger.warning("GroqTTS initialized without an API key! TTS will fail.")

    @staticmethod
    def _wav_to_mulaw_8k(wav_bytes: bytes) -> bytes:
        """Decode a WAV buffer and emit 8kHz mono µ-law bytes for Twilio."""
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            sampwidth = wf.getsampwidth()
            framerate = wf.getframerate()
            channels = wf.getnchannels()
            pcm = wf.readframes(wf.getnframes())

        # Groq returns 16-bit PCM, but be defensive.
        if sampwidth != 2:
            pcm = audioop.lin2lin(pcm, sampwidth, 2)
            sampwidth = 2

        if channels == 2:
            pcm = audioop.tomono(pcm, sampwidth, 1, 1)

        if framerate != TWILIO_SAMPLE_RATE:
            pcm, _ = audioop.ratecv(pcm, sampwidth, 1, framerate, TWILIO_SAMPLE_RATE, None)

        return audioop.lin2ulaw(pcm, sampwidth)

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.client:
            logger.error("🚫 [GroqTTS] API Key missing / client not initialized.")
            return
        if not text or not text.strip():
            return

        start = time.time()

        def _call():
            # Groq only supports response_format=wav; we convert to 8kHz µ-law below.
            return self.client.audio.speech.create(
                model=self.model,
                voice=self.voice_id,
                input=text,
                response_format="wav",
            )

        try:
            resp = await asyncio.to_thread(_call)
            wav_bytes = await asyncio.to_thread(resp.read)
            if not wav_bytes:
                logger.warning("⚠️ [GroqTTS] Empty audio returned.")
                return

            mulaw_bytes = await asyncio.to_thread(self._wav_to_mulaw_8k, wav_bytes)

            self.last_latency = time.time() - start
            await communicator.send_media(base64.b64encode(mulaw_bytes).decode("utf-8"))
            logger.info(
                "✅ [GroqTTS] Sent audio. latency: %.2fs, wav=%d mulaw=%d",
                self.last_latency,
                len(wav_bytes),
                len(mulaw_bytes),
            )
        except Exception as exc:
            logger.error("❌ [GroqTTS] Synthesis error: %s", exc)
