import asyncio
import io
import logging
from utils.config import async_cartesia_client, DEEPGRAM_API_KEY

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self):
        pass

    async def transcribe(self, audio_generator, engine_type: str, encoding: str, sample_rate: int):
        """
        Generic transcribe method that routes to the correct provider.
        """
        if engine_type == "mistral-cartesia":
            async for result in self._cartesia_transcribe(audio_generator, encoding, sample_rate):
                yield result
        elif engine_type == "mistral-deepgram":
            async for result in self._deepgram_transcribe(audio_generator, encoding, sample_rate):
                yield result
        else:
            logger.warning(f"⚠️ Unsupported STT engine: {engine_type}")

    async def _cartesia_transcribe(self, audio_generator, encoding: str, sample_rate: int):
        """Cartesia Ink-Whisper STT (SDK 3.0.0).
        
        The SDK 3.0.0 stt resource does NOT have websocket_connect.
        It only has stt.transcribe() which accepts a bytes/file-like object.
        We buffer all audio chunks and then call transcribe().
        
        For low-latency real-time transcription, prefer 'mistral-deepgram' engine.
        """
        try:
            # Collect all audio chunks into a buffer
            buffer = io.BytesIO()
            async for chunk in audio_generator:
                if chunk:
                    buffer.write(chunk)
            
            buffer.seek(0)
            audio_bytes = buffer.read()

            if not audio_bytes:
                logger.warning("⚠️ [Cartesia STT] No audio data received")
                return

            # SDK 3.0.0: stt.transcribe() is a coroutine returning a response object
            response = await async_cartesia_client.stt.transcribe(
                model="ink-whisper",
                file=("audio.wav", audio_bytes, "audio/wav"),
                encoding=encoding,
                sample_rate=sample_rate,
                language="en",
            )
            
            # The response in SDK 3.0.0 is a TranscribeResponse with a 'text' field
            transcript = getattr(response, "text", "") or getattr(response, "transcript", "")
            if transcript:
                yield {"transcript": transcript, "is_final": True}

        except Exception as e:
            logger.error(f"❌ [Cartesia STT] Error: {e}")

    async def _deepgram_transcribe(self, audio_generator, encoding: str, sample_rate: int):
        """Deepgram STT (Streaming)."""
        # Placeholder — Deepgram streaming is handled in voice_pipeline directly
        pass
