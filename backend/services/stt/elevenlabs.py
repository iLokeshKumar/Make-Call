import asyncio
import json
import logging
import aiohttp
import audioop
from typing import AsyncGenerator, Dict, Any

logger = logging.getLogger(__name__)

class ElevenLabsSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "ElevenLabs"
        self.model = model or "scribe_v1"
        self.api_key = api_key
        
        if not self.api_key:
            logger.warning("ElevenLabsSTT initialized without an API key! Transcription will fail.")

    async def transcribe(self, audio_generator, encoding: str = "linear16", sample_rate: int = 8000) -> AsyncGenerator[Dict[str, Any], None]:
        url = f"wss://api.elevenlabs.io/v1/stt/stream?model_id={self.model}"
        headers = {"xi-api-key": self.api_key}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(url, headers=headers) as ws:
                    async def sender():
                        resample_state = None
                        try:
                            async for chunk in audio_generator:
                                if chunk:
                                    # Convert mulaw 8k to pcm 16k for ElevenLabs Scribe
                                    pcm_8k = audioop.ulaw2lin(chunk, 2)
                                    pcm_16k, resample_state = audioop.ratecv(pcm_8k, 2, 1, 8000, 16000, resample_state)
                                    await ws.send_bytes(pcm_16k)
                            await ws.send_json({"type": "CloseStream"})
                        except Exception as e:
                            logger.error(f"❌ [ElevenLabsSTT] Send error: {e}")

                    async def receiver():
                        try:
                            async for msg in ws:
                                if msg.type == aiohttp.WSMsgType.TEXT:
                                    data = json.loads(msg.data)
                                    if "text" in data:
                                        transcript = data["text"].strip()
                                        is_final = data.get("is_final", False)
                                        
                                        if transcript:
                                            yield {"transcript": transcript, "is_final": is_final, "type": "transcript"}
                                    
                                    if data.get("type") == "EndOfTurn":
                                        yield {"type": "end_of_turn"}
                                elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                                    break
                        except Exception as e:
                            logger.error(f"❌ [ElevenLabsSTT] Receive error: {e}")

                    send_task = asyncio.create_task(sender())
                    try:
                        async for result in receiver():
                            yield result
                    finally:
                        send_task.cancel()
            except Exception as e:
                logger.error(f"❌ [ElevenLabsSTT] Connection error: {e}")