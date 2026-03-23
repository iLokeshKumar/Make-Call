import asyncio
import io
import logging
import json
import websockets
import aiohttp
from credentials_service import get_credential

try:
    from sarvamai import AsyncSarvamAI
    SARVAM_AVAILABLE = True
except ImportError:
    SARVAM_AVAILABLE = False

try:
    from services.sarvam_stt import SarvamSTT
    SARVAM_REST_AVAILABLE = True
except ImportError:
    SARVAM_REST_AVAILABLE = False

try:
    from services.cartesia_stt import CartesiaSTT
    CARTESIA_REST_AVAILABLE = True
except ImportError:
    CARTESIA_REST_AVAILABLE = False

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self):
        self.last_provider = None
        self.last_model = None

    async def transcribe(self, audio_generator, engine_type: str, encoding: str = "linear16", sample_rate: int = 8000):
        """
        Generic transcribe method that routes to the correct provider.
        """
        if engine_type == "mistral-cartesia":
            async for result in self._cartesia_streaming_transcribe(audio_generator, encoding, sample_rate):
                yield result
        elif engine_type == "mistral-sarvam":
            async for result in self._sarvam_streaming_transcribe(audio_generator, encoding, sample_rate):
                yield result
        elif engine_type in ["mistral-deepgram", "mistral-deepgram-cartesia", "mistral-elevenlabs"]:
            async for result in self._deepgram_flux_transcribe(audio_generator, encoding, sample_rate):
                yield result
        else:
            logger.warning(f"⚠️ Unsupported STT engine: {engine_type}")

    async def _cartesia_streaming_transcribe(self, audio_generator, encoding: str = "pcm_mulaw", sample_rate: int = 8000):
        """Utterance-based Cartesia STT using REST API + Local VAD (8kHz Mulaw support)."""
        if not CARTESIA_REST_AVAILABLE:
            logger.error("❌ cartesia_stt.py helper missing.")
            yield {"transcript": "[Error: Cartesia Helper Missing]", "is_final": True}
            return

        CARTESIA_API_KEY = get_credential("CARTESIA_API_KEY")
        if not CARTESIA_API_KEY:
            logger.error("❌ CARTESIA_API_KEY missing.")
            yield {"transcript": "[Error: Cartesia API Key Missing]", "is_final": True}
            return

        self.last_provider = "Cartesia"
        self.last_model = "sonic-3"
        
        # Initialize helper with aggressiveness Level 1 (standard)
        stt_helper = CartesiaSTT(api_key=CARTESIA_API_KEY)
        import audioop
        resample_state = None
        chunk_count = 0
        try:
            async for chunk in audio_generator:
                if not chunk: continue
                chunk_count += 1
                
                # 1. Convert to Linear16
                if encoding == "pcm_mulaw":
                    linear_8k = audioop.ulaw2lin(chunk, 2)
                #elif encoding == "linear16":
                #    linear_8k = chunk
                else:
                    linear_8k = chunk

                # 2. Upsample from 8kHz to 16kHz for accurate VAD
                try:
                    linear_16k, resample_state = audioop.ratecv(linear_8k, 2, 1, 8000, 16000, resample_state)
                except Exception as e:
                    logger.error(f"❌ Rate conversion (Cartesia) failed: {e}")
                    continue
                
                # 3. Process through VAD + Buffering
                if stt_helper.process_chunk(linear_16k):
                    # Utterance complete (silence detected)
                    transcript = await stt_helper.transcribe()
                    if transcript:
                        yield {"transcript": transcript, "is_final": True}
                        
            # 4. Final flush
            if stt_helper._speech_buffer:
                transcript = await stt_helper.transcribe()
                if transcript:
                    yield {"transcript": transcript, "is_final": True}

        except Exception as e:
            logger.error(f"❌ Cartesia STT Core Error: {e}")
        finally:
            logger.info(f"🎤 Cartesia STT session finished. Processed {chunk_count} chunks.")

    async def _sarvam_streaming_transcribe(self, audio_generator, encoding: str = "pcm_mulaw", sample_rate: int = 8000):
        """Utterance-based Sarvam AI STT using REST API + Local VAD (8kHz Mulaw support)."""
        if not SARVAM_REST_AVAILABLE:
            logger.error("❌ sarvam_stt.py helper missing.")
            yield {"transcript": "[Error: Sarvam Helper Missing]", "is_final": True}
            return

        SARVAM_API_KEY = get_credential("SARVAM_API_KEY")
        if not SARVAM_API_KEY:
            logger.error("❌ SARVAM_API_KEY missing.")
            yield {"transcript": "[Error: Sarvam API Key Missing]", "is_final": True}
            return

        self.last_provider = "Sarvam"
        self.last_model = "bulbul:v3"

        # Initialize helper with aggressiveness Level 1 (standard)
        stt_helper = SarvamSTT(api_key=SARVAM_API_KEY, language="en-IN")
        import audioop
        resample_state = None
        chunk_count = 0
        try:
            async for chunk in audio_generator:
                if not chunk: continue
                chunk_count += 1
                
                # 1. Convert to Linear16
                if encoding == "pcm_mulaw":
                    linear_8k = audioop.ulaw2lin(chunk, 2)
                #elif encoding == "linear16":
                #    linear_8k = chunk
                else:
                    linear_8k = chunk

                # 2. Upsample from 8kHz to 16kHz for accurate VAD
                try:
                    linear_16k, resample_state = audioop.ratecv(linear_8k, 2, 1, 8000, 16000, resample_state)
                except Exception as e:
                    logger.error(f"❌ Rate conversion (Sarvam) failed: {e}")
                    continue
                
                # 3. Process through VAD + Buffering
                if stt_helper.process_chunk(linear_16k):
                    # Utterance complete (silence detected)
                    transcript = await stt_helper.transcribe()
                    if transcript:
                        yield {"transcript": transcript, "is_final": True}
                        
            # 4. Final flush
            if stt_helper._speech_buffer:
                transcript = await stt_helper.transcribe()
                if transcript:
                    yield {"transcript": transcript, "is_final": True}

        except Exception as e:
            logger.error(f"❌ Sarvam STT Core Error: {e}")
        finally:
            logger.info(f"🎤 Sarvam STT session finished. Processed {chunk_count} chunks.")

    async def _deepgram_transcribe(self, audio_generator, encoding: str, sample_rate: int):
        """Deepgram STT (Streaming)."""
        pass

    async def _deepgram_flux_transcribe(self, audio_generator, encoding: str = "linear16", sample_rate: int = 8000):
        """Deepgram STT (Streaming) using stable aiohttp pattern."""
        dg_encoding = "mulaw" if "mulaw" in encoding else encoding
        
        logger.info(f"🎙️ Deepgram STT using: {dg_encoding} @ {sample_rate}Hz")
        self.last_provider = "Deepgram"
        self.last_model = "nova-2"
        
        DEEPGRAM_API_KEY = get_credential("DEEPGRAM_API_KEY")
        url = f"wss://api.deepgram.com/v1/listen?model=nova-2&encoding={dg_encoding}&sample_rate={sample_rate}&interim_results=true"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(url, headers=headers) as ws:
                    logger.info("🎯 Deepgram WebSocket Connected")
                    
                    async def sender():
                        try:
                            async for chunk in audio_generator:
                                if chunk:
                                    await ws.send_bytes(chunk)
                            await ws.send_json({"type": "CloseStream"})
                        except Exception as e:
                            logger.error(f"❌ Deepgram send error: {e}")

                    async def receiver():
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if "channel" in data:
                                        alt = data["channel"]["alternatives"][0]
                                        transcript = alt.get("transcript", "").strip()
                                        is_final = data.get("is_final", False)
                                        
                                        if transcript:
                                            yield {"transcript": transcript, "is_final": is_final, "type": "transcript"}
                                    
                                    if data.get("type") == "EndOfTurn":
                                        yield {"type": "end_of_turn"}
                                        
                                elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                                    break
                        except Exception as e:
                            logger.error(f"❌ Deepgram receive error: {e}")

                    send_task = asyncio.create_task(sender())
                    try:
                        async for result in receiver():
                            yield result
                    finally:
                        send_task.cancel()
                        
            except Exception as e:
                logger.error(f"❌ Deepgram connection error: {e}")
