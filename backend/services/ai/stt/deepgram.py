import asyncio
import json
import logging
import aiohttp
from typing import AsyncGenerator, Dict, Any

logger = logging.getLogger(__name__)

class DeepgramSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Deepgram"
        self.model = model or "nova-2"
        self.api_key = api_key
        
        if not self.api_key:
            logger.warning("DeepgramSTT initialized without an API key! Transcription will fail.")

    async def transcribe(self, audio_generator, encoding: str = "linear16", sample_rate: int = 8000) -> AsyncGenerator[Dict[str, Any], None]:
        dg_encoding = "mulaw" if "mulaw" in encoding else encoding
        url = f"wss://api.deepgram.com/v1/listen?model={self.model}&encoding={dg_encoding}&sample_rate={sample_rate}&interim_results=true"
        headers = {"Authorization": f"Token {self.api_key}"}
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.ws_connect(url, headers=headers) as ws:
                    async def sender():
                        try:
                            async for chunk in audio_generator:
                                if chunk:
                                    await ws.send_bytes(chunk)
                            await ws.send_json({"type": "CloseStream"})
                        except Exception as e:
                            logger.error(f"❌ [DeepgramSTT] Send error: {e}")

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
                            logger.error(f"❌ [DeepgramSTT] Receive error: {e}")

                    send_task = asyncio.create_task(sender())
                    try:
                        async for result in receiver():
                            yield result
                    finally:
                        send_task.cancel()
            except Exception as e:
                logger.error(f"❌ [DeepgramSTT] Connection error: {e}")
