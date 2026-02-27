import io
import wave
import httpx
import webrtcvad
import logging
from collections import deque

logger = logging.getLogger(__name__)

class SarvamSTT:
    def __init__(self, api_key: str, language: str = "en-IN", aggressiveness: int = 1):
        """
        Initializes the Sarvam REST STT helper with WebRTC VAD.
        
        Args:
            api_key: Sarvam AI API subscription key.
            language: Target language code (e.g., 'en-IN').
            aggressiveness: VAD sensitivity (0-3). 1 is standard.
        """
        self.api_key = api_key
        self.language = language
        self.vad = webrtcvad.Vad(aggressiveness)
        self.buffer: list[bytes] = []
        self.silence_frames = 0
        self.is_recording = False
        
        # 30 frames of 20ms = 600ms of silence to trigger utterance end
        self.SILENCE_THRESHOLD = 30 

    def process_chunk(self, pcm16k: bytes) -> bool:
        """
        Feed 16kHz PCM data.
        Returns True when an utterance is complete (silence detected).
        """
        # VAD expects exactly 10ms, 20ms, or 30ms frames at 16kHz.
        # 20ms = 320 samples = 640 bytes.
        frame_size = 640
        frames = [pcm16k[i:i+frame_size] for i in range(0, len(pcm16k), frame_size)]
        
        for frame in frames:
            if len(frame) < frame_size:
                continue
            
            is_speech = self.vad.is_speech(frame, 16000)
            
            if is_speech:
                if not self.is_recording:
                    logger.info("🔊 Speech started...")
                    self.is_recording = True
                self.buffer.append(frame)
                self.silence_frames = 0
            elif self.is_recording:
                self.silence_frames += 1
                self.buffer.append(frame) # Keep some silence frames for context
                if self.silence_frames >= self.SILENCE_THRESHOLD:
                    logger.info("🤫 Silence detected. Utterance complete.")
                    self.is_recording = False
                    return True
        return False

    def get_wav_bytes(self) -> bytes:
        """Converts buffered PCM into a WAV file in memory."""
        audio_data = b"".join(self.buffer)
        self.buffer = []
        self.silence_frames = 0
        
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2) # 16-bit
            wf.setframerate(16000)
            wf.writeframes(audio_data)
        
        return buf.getvalue()

    async def transcribe(self) -> str:
        """
        Sends the buffered audio to Sarvam REST API and returns the transcript.
        """
        wav_bytes = self.get_wav_bytes()
        if not wav_bytes or len(wav_bytes) < 1000: # Ignore tiny noise
            return ""
            
        logger.info(f"📡 Transcribing {len(wav_bytes)} bytes via Sarvam REST API...")
        
        async with httpx.AsyncClient(timeout=15.0) as client:
            try:
                resp = await client.post(
                    "https://api.sarvam.ai/speech-to-text",
                    headers={"api-subscription-key": self.api_key},
                    files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                    data={
                        "language_code": self.language,
                        "model": "saarika:v2", # More stable for REST
                        "with_timestamps": "false",
                    }
                )
                resp.raise_for_status()
                result = resp.json()
                transcript = result.get("transcript", "").strip()
                logger.info(f"🛰️ Transcript: '{transcript}'")
                return transcript
            except Exception as e:
                logger.error(f"❌ Sarvam REST error: {e}")
                return ""
