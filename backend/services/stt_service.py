import asyncio
import io
import logging
import json
import websockets
import aiohttp
from utils.config import DEEPGRAM_API_KEY, CARTESIA_API_KEY, CARTESIA_VOICE_ID

logger = logging.getLogger(__name__)

class STTService:
    def __init__(self):
        pass

    async def transcribe(self, audio_generator, engine_type: str, encoding: str = "linear16", sample_rate: int = 16000):
        """
        Generic transcribe method that routes to the correct provider.
        """
        if engine_type == "mistral-cartesia":
            async for result in self._cartesia_streaming_transcribe(audio_generator, encoding, sample_rate):
                yield result
        elif engine_type in ["mistral-deepgram", "mistral-deepgram-cartesia", "mistral-elevenlabs", "mistral-sarvam"]:
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

    async def _deepgram_transcribe(self, audio_generator, encoding: str, sample_rate: int):
        """Deepgram STT (Streaming)."""
        # Placeholder — Deepgram streaming is handled in voice_pipeline directly
        pass

    async def _deepgram_flux_transcribe(self, audio_generator, encoding: str = "linear16", sample_rate: int = 16000):
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
