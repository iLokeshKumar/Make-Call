import io
import wave
import httpx
import logging
import struct
import math

logger = logging.getLogger(__name__)

class CartesiaSTT:
    """
    Utterance-based Cartesia STT using RMS energy VAD.
    Works reliably on upsampled mulaw telephone audio.
    """

    # Tuning constants
    SPEECH_RMS_THRESHOLD = 150    # RMS above this = speech (tune if needed)
    SILENCE_FRAMES_NEEDED = 15    # consecutive silent frames to end utterance (~450ms at 30ms frames)
    MIN_SPEECH_FRAMES = 5         # minimum speech frames before we'll transcribe (~150ms)

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._incoming = b""
        self._speech_buffer = b""
        self.silence_counter = 0
        self.speech_frame_count = 0
        self.is_speech_active = False

    @staticmethod
    def _rms(frame: bytes) -> float:
        """Calculate RMS energy of a PCM16 frame."""
        if len(frame) < 2:
            return 0.0
        samples = struct.unpack(f"<{len(frame)//2}h", frame)
        return math.sqrt(sum(s * s for s in samples) / len(samples))

    def process_chunk(self, pcm_16k: bytes) -> bool:
        """
        Feed 16kHz PCM. Returns True when utterance ends.
        Uses RMS energy — reliable on any telephone audio.
        """
        self._incoming += pcm_16k
        frame_size = 960  # 30ms @ 16kHz

        while len(self._incoming) >= frame_size:
            frame = self._incoming[:frame_size]
            self._incoming = self._incoming[frame_size:]

            rms = self._rms(frame)
            logger.debug(f"🔊 [Cartesia] RMS: {rms:.0f}")
            is_speech = rms > self.SPEECH_RMS_THRESHOLD

            if is_speech:
                if not self.is_speech_active:
                    logger.info(f"🔊 [Cartesia] Speech started (RMS: {rms:.0f})")
                self.is_speech_active = True
                self.silence_counter = 0
                self.speech_frame_count += 1
                self._speech_buffer += frame

            elif self.is_speech_active:
                self._speech_buffer += frame  # keep trailing silence for context
                self.silence_counter += 1

                if self.silence_counter >= self.SILENCE_FRAMES_NEEDED:
                    if self.speech_frame_count >= self.MIN_SPEECH_FRAMES:
                        logger.info(f"🤫 [Cartesia] Utterance complete. Speech frames: {self.speech_frame_count}")
                        self.silence_counter = 0
                        self.speech_frame_count = 0
                        self.is_speech_active = False
                        return True
                    else:
                        # Too short — was just noise, reset
                        logger.debug(f"[Cartesia] Noise burst ignored ({self.speech_frame_count} frames)")
                        self._speech_buffer = b""
                        self.silence_counter = 0
                        self.speech_frame_count = 0
                        self.is_speech_active = False

        return False

    async def transcribe(self) -> str:
        if not self._speech_buffer:
            return ""

        audio_to_send = self._speech_buffer
        self._speech_buffer = b""

        wav_io = io.BytesIO()
        try:
            with wave.open(wav_io, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(audio_to_send)
        except Exception as e:
            logger.error(f"❌ WAV creation error: {e}")
            return ""

        wav_io.seek(0)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.cartesia.ai/stt",
                    files={"file": ("audio.wav", wav_io.getvalue(), "audio/wav")},
                    data={"model": "ink-whisper", "language": "en"},
                    headers={
                        "X-API-Key": self.api_key,
                        "Cartesia-Version": "2025-04-16"
                    },
                )
                if response.status_code != 200:
                    logger.error(f"❌ Cartesia STT {response.status_code}: {response.text}")
                    return ""
                result = response.json()
                logger.info(f"🔍 [Cartesia STT Raw Response] {result}")
                transcript = (result.get("text") or result.get("transcript") or "").strip()
                if transcript:
                    logger.info(f"🛰️ [Cartesia STT] '{transcript}'")
                return transcript
        except Exception as e:
            logger.error(f"❌ Cartesia STT error: {e}")
            return ""

    async def close(self):
        self._incoming = b""
        self._speech_buffer = b""