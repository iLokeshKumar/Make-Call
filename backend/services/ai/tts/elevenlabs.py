import base64
import logging
import os
import json
import time
import aiohttp

logger = logging.getLogger(__name__)


class ElevenLabsTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "ElevenLabs"

        db_model = os.getenv("ELEVENLABS_TTS_MODEL")
        if model and ("eleven_" in model or "multilingual" in model):
            self.model = model
        else:
            self.model = db_model or "eleven_turbo_v2_5"

        self.api_key = api_key
        self.voice_id = voice_id or os.getenv("ELEVENLABS_VOICE_ID") or "CwhOLp6mAE7h9asvUURR"
        self.last_latency = 0

        if not self.api_key:
            logger.warning("ElevenLabsTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [ElevenLabsTTS] API Key missing!")
            return

        if ws_to_use:
            logger.info(f"🎧 [ElevenLabsTTS] Using WebSocket for: '{text[:60]}...'")
            await self._speak_ws(text, communicator, ws_to_use)
            return

        logger.info(f"🎧 [ElevenLabsTTS] Using REST API for: '{text[:60]}...'")
        await self._speak_http(text, communicator, aiohttp_session)

    async def _speak_http(self, text: str, communicator, aiohttp_session=None):
        start_time = time.time()
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
        headers = {
            "xi-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        params = {"output_format": "ulaw_8000"}
        payload = {"text": text, "model_id": self.model}

        session = aiohttp_session or aiohttp.ClientSession()
        should_close = aiohttp_session is None
        try:
            async with session.post(url, json=payload, params=params, headers=headers) as resp:
                if resp.status != 200:
                    error = await resp.text()
                    logger.error(f"❌ [ElevenLabsTTS] REST API Error {resp.status}: {error}")
                    return
                audio_bytes = await resp.read()
                first_byte_time = time.time() - start_time
                await communicator.send_media(base64.b64encode(audio_bytes).decode())
                self.last_latency = first_byte_time
                logger.info(f"🔊 [ElevenLabsTTS REST] Done. Latency: {first_byte_time:.3f}s | Bytes: {len(audio_bytes)}")
        except Exception as e:
            logger.error(f"❌ [ElevenLabsTTS REST] Error: {e}")
        finally:
            if should_close:
                await session.close()

    async def _speak_ws(self, text: str, communicator, ws, is_final=True):
        logger.info(f"🔊 [ElevenLabsTTS WS] Streaming chunk: '{text[:20]}...' (final={is_final})")
        start_time = time.time()
        first_byte_time = None
        try:
            # Send text chunk
            await ws.send_json({"text": text})
            if is_final:
                # Only flush if we are done with the logical turn
                await ws.send_json({"text": "", "flush": True})
            
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    audio_b64 = data.get("audio")
                    if audio_b64:
                        if first_byte_time is None:
                            first_byte_time = time.time() - start_time
                            self.last_latency = first_byte_time
                        audio_bytes = base64.b64decode(audio_b64)
                        await communicator.send_media(base64.b64encode(audio_bytes).decode())
                    
                    # ElevenLabs sends 'isFinal' when a flush is completed or context ends
                    if data.get("isFinal"):
                        break
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    if first_byte_time is None:
                        first_byte_time = time.time() - start_time
                        self.last_latency = first_byte_time
                    await communicator.send_media(base64.b64encode(msg.data).decode())
                elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    break
        except Exception as e:
            logger.error(f"❌ [ElevenLabsTTS WS] Error: {e}")
