import io
import wave
import httpx
import logging
import struct
import math

logger = logging.getLogger(__name__)

class SarvamSTT:
    """
    Utterance-based Sarvam STT using RMS energy VAD.
    Works reliably on upsampled mulaw telephone audio.
    """

    SPEECH_RMS_THRESHOLD = 150
    SILENCE_FRAMES_NEEDED = 20    # ~400ms at 20ms frames
    MIN_SPEECH_FRAMES = 5         # ~100ms minimum

    def __init__(self, api_key: str, language: str = "en-IN"):
        self.api_key = api_key
        self.language = language
        self._incoming = b""
        self._speech_buffer = b""
        self.silence_counter = 0
        self.speech_frame_count = 0
        self.is_speech_active = False

    @staticmethod
    def _rms(frame: bytes) -> float:
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
        frame_size = 640  # 20ms @ 16kHz

        while len(self._incoming) >= frame_size:
            frame = self._incoming[:frame_size]
            self._incoming = self._incoming[frame_size:]

            rms = self._rms(frame)
            logger.debug(f"🔊 [Sarvam] RMS: {rms:.0f}")
            is_speech = rms > self.SPEECH_RMS_THRESHOLD

            if is_speech:
                if not self.is_speech_active:
                    logger.info(f"🔊 [Sarvam] Speech started (RMS: {rms:.0f})")
                self.is_speech_active = True
                self.silence_counter = 0
                self.speech_frame_count += 1
                self._speech_buffer += frame

            elif self.is_speech_active:
                self._speech_buffer += frame
                self.silence_counter += 1

                if self.silence_counter >= self.SILENCE_FRAMES_NEEDED:
                    if self.speech_frame_count >= self.MIN_SPEECH_FRAMES:
                        logger.info(f"🤫 [Sarvam] Utterance complete. Speech frames: {self.speech_frame_count}")
                        self.silence_counter = 0
                        self.speech_frame_count = 0
                        self.is_speech_active = False
                        return True
                    else:
                        logger.debug(f"[Sarvam] Noise burst ignored ({self.speech_frame_count} frames)")
                        self._speech_buffer = b""
                        self.silence_counter = 0
                        self.speech_frame_count = 0
                        self.is_speech_active = False

        return False

    def _get_wav_bytes(self) -> bytes:
        audio_data = self._speech_buffer
        self._speech_buffer = b""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            wf.writeframes(audio_data)
        return buf.getvalue()

    async def transcribe(self) -> str:
        wav_bytes = self._get_wav_bytes()
        if len(wav_bytes) < 1000:
            return ""

        logger.info(f"📡 [Sarvam] Sending {len(wav_bytes)} bytes...")
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.sarvam.ai/speech-to-text",
                    headers={"api-subscription-key": self.api_key},
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                    data={
                        "language_code": self.language,
                        "model": "saarika:v2.5",
                        "with_timestamps": "false",
                    }
                )
                resp.raise_for_status()
                transcript = resp.json().get("transcript", "").strip()
                if transcript:
                    logger.info(f"🛰️ [Sarvam STT] '{transcript}'")
                return transcript
        except Exception as e:
            logger.error(f"❌ Sarvam REST error: {e}")
            return ""