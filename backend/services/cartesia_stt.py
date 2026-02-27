import io
import wave
import httpx
import logging
import webrtcvad

logger = logging.getLogger(__name__)

class CartesiaSTT:
    """Robust utterance-based Cartesia STT using REST and local VAD."""
    
    def __init__(self, api_key: str, aggressiveness: int = 1):
        self.api_key = api_key
        # WebRTC VAD (0: least aggressive, 3: most aggressive)
        self.vad = webrtcvad.Vad(aggressiveness)
        self.buffer = b""
        self.silence_counter = 0
        
    def process_chunk(self, pcm_16k: bytes) -> bool:
        """
        Processes a chunk of 16kHz linear PCM audio.
        Returns True if a complete utterance (silence) is detected.
        """
        self.buffer += pcm_16k
        
        # WebRTCVAD needs 10ms, 20ms, or 30ms frames.
        # At 16kHz, 30ms = 480 samples = 960 bytes (16-bit)
        frame_size = 960 
        
        if len(self.buffer) < frame_size:
            return False
            
        # Check the latest 30ms frame for speech activity
        latest_frame = self.buffer[-frame_size:]
        try:
            is_speech = self.vad.is_speech(latest_frame, 16000)
        except Exception as e:
            logger.error(f"❌ VAD error: {e}")
            return False
            
        if not is_speech:
            self.silence_counter += 1
        else:
            self.silence_counter = 0
            
        # ~600ms of continuous silence (20 frames of 30ms) triggers transcription
        if self.silence_counter > 20: 
            self.silence_counter = 0
            return True
            
        return False

    async def transcribe(self) -> str:
        """Sends the current audio buffer to Cartesia REST API for transcription."""
        if not self.buffer:
            return ""

        # Create WAV file in memory
        wav_io = io.BytesIO()
        try:
            with wave.open(wav_io, 'wb') as wav_file:
                wav_file.setnchannels(1)
                wav_file.setsampwidth(2) # 16-bit
                wav_file.setframerate(16000)
                wav_file.writeframes(self.buffer)
        except Exception as e:
            logger.error(f"❌ WAV creation error: {e}")
            return ""
        
        wav_io.seek(0)
        audio_data = wav_io.getvalue()
        self.buffer = b"" # Reset buffer after reading

        try:
            async with httpx.AsyncClient() as client:
                # Cartesia REST STT expects multipart/form-data
                files = {'file': ('audio.wav', audio_data, 'audio/wav')}
                headers = {
                    "X-API-Key": self.api_key,
                    "Cartesia-Version": "2025-04-16"
                }
                
                # Parameters for transcription
                data = {
                    "model": "ink-whisper",
                    "language": "en",
                    "encoding": "pcm_s16le"
                }
                
                response = await client.post(
                    "https://api.cartesia.ai/stt",
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=30.0
                )
                
                if response.status_code != 200:
                    logger.error(f"❌ Cartesia STT Request Failed: {response.status_code} - {response.text}")
                    return ""
                    
                result = response.json()
                transcript = result.get("transcript", "").strip()
                if transcript:
                    logger.info(f"🛰️ Cartesia STT Result: {transcript}")
                return transcript
        except Exception as e:
            logger.error(f"❌ Cartesia REST STT Network Error: {e}")
            return ""

    async def close(self):
        """Cleanup."""
        self.buffer = b""