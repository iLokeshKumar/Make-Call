import logging
import audioop
from typing import AsyncGenerator, Dict, Any
from services.cartesia_stt import CartesiaSTT as CartesiaSTTHelper

from utils import settings_cache

logger = logging.getLogger(__name__)

class CartesiaSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Cartesia"
        self.model = model or settings_cache.get("CARTESIA_STT_MODEL") or "ink-whisper"
        self.api_key = api_key
        
        if not self.api_key:
            logger.warning("CartesiaSTT initialized without an API key! Transcription will fail.")

    async def transcribe(self, audio_generator, encoding: str = "pcm_mulaw", sample_rate: int = 8000) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [CartesiaSTT] API Key missing.")
            yield {"transcript": "[Error: Cartesia API Key Missing]", "is_final": True}
            return

        stt_helper = CartesiaSTTHelper(api_key=self.api_key, model=self.model)
        resample_state = None
        
        try:
            async for chunk in audio_generator:
                if not chunk: continue
                
                # 1. Convert to Linear16
                if "mulaw" in encoding:
                    linear_8k = audioop.ulaw2lin(chunk, 2)
                else:
                    linear_8k = chunk

                # 2. Upsample to 16kHz for VAD
                linear_16k, resample_state = audioop.ratecv(linear_8k, 2, 1, 8000, 16000, resample_state)
                
                # 3. Process Chunk (VAD + Buffering)
                if stt_helper.process_chunk(linear_16k):
                    transcript = await stt_helper.transcribe()
                    if transcript:
                        yield {"transcript": transcript, "is_final": True}
            
            # Final flush
            if stt_helper._speech_buffer:
                transcript = await stt_helper.transcribe()
                if transcript:
                    yield {"transcript": transcript, "is_final": True}

        except Exception as e:
            logger.error(f"❌ [CartesiaSTT] Core Error: {e}")
