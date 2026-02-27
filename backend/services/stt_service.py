import asyncio
import io
import logging
import json
import websockets
import aiohttp
from utils.config import DEEPGRAM_API_KEY, CARTESIA_API_KEY, CARTESIA_VOICE_ID, SARVAM_API_KEY

try:
    from sarvamai import AsyncSarvamAI
    SARVAM_AVAILABLE = True
except ImportError:
    SARVAM_AVAILABLE = False

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self):
        pass

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

    async def _cartesia_streaming_transcribe(self, audio_generator, encoding = "pcm_s16le", sample_rate = "16000"):
        """Real-time Cartesia Ink-Whisper STT with Auto-Reconnect."""
        api_key = CARTESIA_API_KEY
        version = "2025-04-16"
        url = f"wss://api.cartesia.ai/stt/websocket?api_key={api_key}&cartesia_version={version}"
        
        retry_count = 0
        max_retries = 5
        
        while retry_count < max_retries:
            try:
                # Use a cleaner version and ensure headers are set
                async with websockets.connect(
                    url, 
                    additional_headers={
                        "User-Agent": "Rio-AI-Voice/1.0"
                    }
                ) as ws:
                    logger.info(f"✅ Cartesia STT Connected (Attempt {retry_count + 1})")
                    
                    # 1. Send Config
                    config = {
                        "model": str("ink-whisper"),
                        "language": str("en"), 
                        "encoding": str(encoding),
                        "sample_rate": str(sample_rate),
                        "min_volume": str(0.5),
                        "max_silence_duration_secs": str(0.5),
                    }
                    for key, value in config.items():
                        print(f"{key}: {value} (type: {type(value).__name__})")
                    await ws.send(json.dumps(config))
                    
                    # Parallel Send/Receive
                    async def send_audio():
                        try:
                            async for chunk in audio_generator:
                                if chunk:
                                    await ws.send(chunk)
                        except Exception as e:
                            logger.error(f"STT Send Error: {e}")
                        finally:
                            try: await ws.send("finalize")
                            except: pass

                    send_task = asyncio.create_task(send_audio())
                    
                    try:
                        while True:
                            message = await ws.recv()
                            # Reset retry count ONLY after successfully receiving a response
                            retry_count = 0 
                            
                            if isinstance(message, bytes): continue
                            
                            data = json.loads(message)
                            if data.get("type") == "transcript":
                                text = data.get("text", "").strip()
                                is_final = data.get("is_final", False)
                                if text:
                                    yield {"transcript": text, "is_final": is_final}
                            elif data.get("type") == "done":
                                break
                            elif data.get("type") == "error":
                                # DIAGNOSTIC: Log the FULL data to find why error is "None"
                                logger.error(f"❌ Cartesia Server Error! Full response: {data}")
                                break
                                
                    except websockets.exceptions.ConnectionClosed as e:
                        logger.warning(f"⚠️ STT Connection Closed: {e.code} {e.reason}")
                        if retry_count + 1 >= max_retries: break
                        raise 
                    finally:
                        send_task.cancel()
                        # Exit outer while loop if we finished without an error that requires retry
                        # We use a trick: if we're here and send_task was NOT cancelled by us, we exit.
                        # Actually, just check if we broke the 'while True' normally.
                        break
                        
            except Exception as e:
                retry_count += 1
                if retry_count >= max_retries:
                    logger.error(f"❌ STT failed after {max_retries} attempts: {e}")
                    break
                
                wait_time = 2 ** retry_count
                logger.info(f"🔄 Reconnecting STT in {wait_time}s... (Total failures: {retry_count})")
                await asyncio.sleep(wait_time)

    # async def _sarvam_streaming_transcribe(self, audio_generator):
    #     """Real-time Sarvam AI STT using SDK."""
    #     if not SARVAM_AVAILABLE:
    #         logger.error("❌ Sarvam SDK not installed. Please run pip install sarvamai")
    #         yield {"transcript": "[Error: Sarvam SDK Missing]", "is_final": True}
    #         return

    #     if not SARVAM_API_KEY:
    #         logger.error("❌ SARVAM_API_KEY missing in background.")
    #         yield {"transcript": "[Error: Sarvam API Key Missing]", "is_final": True}
    #         return

    #     client = AsyncSarvamAI(api_subscription_key=SARVAM_API_KEY)
        
    #     try:
    #         async with client.speech_to_text_streaming.connect(
    #             model="saaras:v3",
    #             mode="transcribe",
    #             language_code="en-IN",
    #             high_vad_sensitivity=True
    #         ) as ws:
    #             logger.info("🎯 Sarvam STT WebSocket Connected")
                
    #             async def sender():
    #                 import base64
    #                 chunk_count = 0
    #                 try:
    #                     async for chunk in audio_generator:
    #                         if chunk:
    #                             chunk_count += 1
    #                             if chunk_count % 50 == 0:
    #                                 logger.info(f"🎤 Sent {chunk_count} audio chunks to Sarvam STT")
    #                             # Sarvam SDK expects base64 encoded audio in transcribe calls
    #                             b64_audio = base64.b64encode(chunk).decode("utf-8")
    #                             await ws.transcribe(audio=b64_audio)
    #                 except Exception as e:
    #                     logger.error(f"❌ Sarvam STT Send Error: {e}")
    #                 finally:
    #                     logger.info(f"🎤 Audio sender finished. Total chunks sent to Sarvam: {chunk_count}")

    #             sender_task = asyncio.create_task(sender())
                
    #             try:
    #                 while True:
    #                     response = await ws.recv()
    #                     if not response:
    #                         break
                        
    #                     logger.info(f"🛰️ Raw Sarvam STT Response: {response} (type: {type(response).__name__})")
                        
    #                     # Handle response format from Sarvam SDK
    #                     if isinstance(response, dict):
    #                         transcript = response.get("transcript", "").strip()
    #                         is_final = response.get("is_final", False)
    #                         if transcript:
    #                             yield {"transcript": transcript, "is_final": is_final}
    #                     elif isinstance(response, str):
    #                         # If it's a direct string, treat it as the transcript
    #                         # Usually streaming transcripts are interim unless specified
    #                         if response.strip():
    #                             yield {"transcript": response.strip(), "is_final": False}
    #                     else:
    #                         logger.warning(f"❓ Unexpected Sarvam response type: {type(response)}")
                
    #             except Exception as e:
    #                 logger.error(f"❌ Sarvam STT Receive Error: {e}")
    #             finally:
    #                 sender_task.cancel()
                    
    #     except Exception as e:
    #         logger.error(f"❌ Sarvam STT Connection Error: {e}")

    async def _sarvam_streaming_transcribe(self, audio_generator, encoding: str = "linear16", sample_rate: int = 8000):
        """Real-time Sarvam AI STT using SDK with audio conversion."""
        if not SARVAM_AVAILABLE:
            logger.error("❌ Sarvam SDK not installed. Please run pip install sarvamai")
            yield {"transcript": "[Error: Sarvam SDK Missing]", "is_final": True}
            return

        if not SARVAM_API_KEY:
            logger.error("❌ SARVAM_API_KEY missing in background.")
            yield {"transcript": "[Error: Sarvam API Key Missing]", "is_final": True}
            return

        client = AsyncSarvamAI(api_subscription_key=SARVAM_API_KEY)
    
        try:
            async with client.speech_to_text_streaming.connect(
                model="saaras:v3",
                mode="transcribe",
                language_code="en-IN",
                high_vad_sensitivity=True,
                vad_signals=True
            ) as ws:
                logger.info("🎯 Sarvam STT WebSocket Connected")

                def create_wav_header(data_size, sample_rate):
                    """Create WAV header manually with fixed parameters."""
                    import struct
                
                    # Fixed parameters for 16-bit mono PCM
                    channels = 1
                    bits_per_sample = 16  # Ensure this is an integer
                
                    # Calculate derived values
                    byte_rate = sample_rate * channels * (bits_per_sample // 8)
                    block_align = channels * (bits_per_sample // 8)
                
                    # Create WAV header
                    header = struct.pack('<4sI4s4sIHHIIHH4sI',
                        b'RIFF',                    # ChunkID
                        36 + data_size,             # ChunkSize (36 + data size)
                        b'WAVE',                    # Format
                        b'fmt ',                    # Subchunk1ID
                        16,                         # Subchunk1Size (16 for PCM)
                        1,                          # AudioFormat (1 = PCM)
                        channels,                   # NumChannels
                        sample_rate,                # SampleRate
                        byte_rate,                  # ByteRate
                        block_align,                # BlockAlign
                        bits_per_sample,            # BitsPerSample
                        b'data',                    # Subchunk2ID
                        data_size                   # Subchunk2Size
                    )
                    return header
            
                async def sender():
                    import base64
                    import io
                    import wave
                    import audioop
                
                    chunk_count = 0
                    try:
                        async for chunk in audio_generator:
                            if chunk:
                                chunk_count += 1
                                if chunk_count % 50 == 0:
                                    logger.info(f"🎤 Sent {chunk_count} audio chunks to Sarvam STT")
                            
                                # Convert audio to WAV format for Sarvam
                                try:
                                    # Convert from mulaw to linear PCM if needed
                                    if encoding == "pcm_mulaw":
                                        # Convert mulaw to linear16
                                        linear_audio = audioop.ulaw2lin(chunk, 2)  # 2 bytes per sample for 16-bit
                                    elif encoding == "linear16":
                                        linear_audio = chunk
                                    else:
                                        logger.warning(f"⚠️ Unsupported encoding for Sarvam: {encoding}, using as-is")
                                        linear_audio = chunk

                                    # Create complete WAV file with header + data
                                    wav_header = create_wav_header(len(linear_audio), sample_rate)
                                    wav_data = wav_header + linear_audio
                                
                                    # Encode to base64
                                    b64_audio = base64.b64encode(wav_data).decode("utf-8")
                                
                                    logger.debug(f"🎵 Created WAV: header={len(wav_header)} + data={len(linear_audio)} = {len(wav_data)} bytes")

                                    # Send as raw PCM to Sarvam
                                    #b64_audio = base64.b64encode(linear_audio).decode("utf-8")
                                
                                    await ws.transcribe(
                                        audio=b64_audio,
                                        encoding="audio/wav",  # Raw PCM 16-bit little-endian
                                        sample_rate=sample_rate
                                    )
                                
                                    # Create WAV format
                                    #wav_buffer = io.BytesIO()
                                    #with wave.open(wav_buffer, 'wb') as wav_file:
                                    #    wav_file.setnchannels(1)  # Mono
                                    #    wav_file.setsampwidth(2)  # 16-bit
                                    #    wav_file.setframerate(sample_rate)  # Use provided sample rate
                                    #    wav_file.writeframes(linear_audio)
                                
                                    #wav_data = wav_buffer.getvalue()
                                    #b64_audio = base64.b64encode(wav_data).decode("utf-8")

                                    logger.debug(f"🎵 Converted {len(chunk)} bytes to {len(wav_data)} bytes WAV")

                                    logger.info(f"🎤 Sending {len(b64_audio)} bytes to Sarvam STT")
                                
                                    
                                
                                except Exception as conv_error:
                                    logger.error(f"❌ Audio conversion error: {conv_error}")
                                    logger.error(f"   Chunk size: {len(chunk) if chunk else 0}, Encoding: {encoding}, Sample rate: {sample_rate}")
                                    continue
                                
                    except Exception as e:
                        logger.error(f"❌ Sarvam STT Send Error: {e}")
                    finally:
                        logger.info(f"🎤 Audio sender finished. Total chunks sent to Sarvam: {chunk_count}")

                sender_task = asyncio.create_task(sender())
            
                try:
                    async for message in ws:
                        logger.info(f"🛰️ Raw Sarvam STT Response: {message}")
                    
                    # Handle different message types
                    if message.get("type") == "speech_start":
                        logger.info("Speech detected")
                    elif message.get("type") == "speech_end":
                        logger.info("Speech ended")
                    elif message.get("type") == "transcript":
                        transcript = message.get("text", "").strip()
                        is_final = message.get("is_final", False)
                        if transcript:
                            yield {"transcript": transcript, "is_final": is_final}
                            
                except Exception as e:
                    logger.error(f"❌ Sarvam STT Receive Error: {e}")
                finally:
                    sender_task.cancel()
                
        except Exception as e:
            logger.error(f"❌ Sarvam STT Connection Error: {e}")
            yield {"transcript": f"[Error: {str(e)}]", "is_final": True}



    async def _deepgram_transcribe(self, audio_generator, encoding: str, sample_rate: int):
        """Deepgram STT (Streaming)."""
        # Placeholder — Deepgram streaming is handled in voice_pipeline directly
        pass

    async def _deepgram_flux_transcribe(self, audio_generator, encoding: str = "linear16", sample_rate: int = 8000):
        """Deepgram STT (Streaming) using stable aiohttp pattern."""
        # Deepgram uses 'mulaw' for 'pcm_mulaw'
        dg_encoding = "mulaw" if "mulaw" in encoding else encoding
        
        logger.info(f"🎙️ Deepgram STT using: {dg_encoding} @ {sample_rate}Hz")
        
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
                                    
                                    # Handle EndOfTurn if available in this model version
                                    if data.get("type") == "EndOfTurn":
                                        yield {"type": "end_of_turn"}
                                        
                                elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                                    break
                        except Exception as e:
                            logger.error(f"❌ Deepgram receive error: {e}")

                    # Run sender and receiver concurrently
                    send_task = asyncio.create_task(sender())
                    try:
                        async for result in receiver():
                            yield result
                    finally:
                        send_task.cancel()
                        
            except Exception as e:
                logger.error(f"❌ Deepgram connection error: {e}")
