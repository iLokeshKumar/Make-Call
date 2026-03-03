import asyncio
import base64
import logging
import time
import json
import aiohttp
import audioop
from typing import Optional
from utils.config import (
    CARTESIA_API_KEY, CARTESIA_VOICE_ID, 
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
    DEEPGRAM_API_KEY, SARVAM_API_KEY
)
from utils.audio import clean_voice_text

logger = logging.getLogger(__name__)

class TTSService:
    def __init__(self):
        self.last_tts_latency = 0
        self.last_provider = None
        self.last_model = None

    async def speak(self, text: str, engine_type: str, communicator, cartesia_ws=None, aiohttp_session=None, deepgram_ws=None, elevenlabs_ws=None, context_id=None):
        """
        Generic speak method that routes to the correct provider.
        """
        text = clean_voice_text(text)
        if not text:
            return

        if engine_type in ["mistral-cartesia", "mistral-deepgram-cartesia"]:
            await self._cartesia_speak(text, communicator, cartesia_ws, context_id)
        elif engine_type == "mistral-sarvam":
            await self._sarvam_speak(text, communicator)
        elif engine_type == "mistral-deepgram":
            await self._deepgram_speak(text, communicator, aiohttp_session, deepgram_ws)
        elif engine_type == "mistral-elevenlabs":
            await self._elevenlabs_speak(text, communicator, aiohttp_session, elevenlabs_ws)
        else:
            logger.warning(f"⚠️ Unsupported TTS engine: {engine_type}")

    async def _cartesia_speak(self, text, communicator, ws_to_use=None, context_id=None):
        """Streaming TTS from Cartesia using direct aiohttp WebSocket."""
        try:
            start_time = time.time()
            tts_first_byte_time = 0
            
            # 1. Prepare Request Dict
            tts_event = {
                "model_id": "sonic-3",
                "transcript": text,
                "voice": {
                    "mode": "id",
                    "id": CARTESIA_VOICE_ID,
                },
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_mulaw",
                    "sample_rate": 8000,
                },
                "language": "en",
                "context_id": context_id or f"ctx_{int(time.time()*1000)}"
            }

            async def _stream_on_ws(ws):
                nonlocal tts_first_byte_time
                await ws.send_json(tts_event)
                
                async for msg in ws:
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(msg.data)
                        audio_b64 = data.get("audio") or data.get("data")
                        if audio_b64:
                            if tts_first_byte_time == 0:
                                tts_first_byte_time = time.time() - start_time
                            await communicator.send_media(audio_b64)
                        
                        if data.get("done"):
                            break
                    elif msg.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                        break

            # 2. Use existing WS or create temporary one
            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                url = f"wss://api.cartesia.ai/tts/websocket?api_key={CARTESIA_API_KEY}&cartesia_version=2025-04-16"
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url) as ws:
                        await _stream_on_ws(ws)

            self.last_tts_latency = tts_first_byte_time
            self.last_provider = "Cartesia"
            self.last_model = "sonic-3"
            logger.info(f"✅ [Cartesia TTS] Complete (aiohttp). First byte: {tts_first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [Cartesia TTS] Error: {e}")

    async def _sarvam_speak(self, text, communicator, aiohttp_session=None):
        """Sarvam AI TTS using aiohttp with mulaw output."""
        if not SARVAM_API_KEY:
            logger.error("❌ SARVAM_API_KEY missing!")
            return

        tts_start_time = time.time()
        tts_first_byte_time = 0
        
        url = "https://api.sarvam.ai/text-to-speech/stream"
        headers = {
            "api-subscription-key": SARVAM_API_KEY,
            "Content-Type": "application/json"
        }
        
        payload = {
            "text": text,
            "target_language_code": "en-IN",
            "speaker": "ritu",
            "model": "bulbul:v3",
            "pace": 1.1,
            "speech_sample_rate": 8000,
            "output_audio_codec": "mulaw",
            "enable_preprocessing": True
        }

        async def _stream_on_response(response):
            nonlocal tts_first_byte_time
            async for chunk in response.content.iter_any():
                if chunk:
                    if tts_first_byte_time == 0:
                        tts_first_byte_time = time.time() - tts_start_time
                    
                    # Sarvam provides raw binary, we need base64 for Twilio
                    payload_b64 = base64.b64encode(chunk).decode("utf-8")
                    await communicator.send_media(payload_b64)

        try:
            session = aiohttp_session or aiohttp.ClientSession()
            should_close = aiohttp_session is None
            try:
                async with session.post(url, headers=headers, json=payload) as response:
                    await _stream_on_response(response)
            finally:
                if should_close:
                    await session.close()
            #if aiohttp_session:
            #    async with aiohttp_session.post(url, headers=headers, json=payload) as response:
            #        await _stream_on_response(response)
            #else:
            #    async with aiohttp.ClientSession() as session:
            #        async with session.post(url, headers=headers, json=payload) as response:
            #            await _stream_on_response(response)
            
            self.last_tts_latency = tts_first_byte_time
            self.last_provider = "Sarvam"
            self.last_model = "bulbul:v3"
            logger.info(f"✅ [Sarvam TTS] Complete. First byte: {tts_first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [Sarvam TTS] Error: {e}")

    async def _deepgram_speak(self, text, communicator, aiohttp_session=None, ws_to_use=None):
        """Deepgram Aura TTS (Streaming via WebSocket)."""
        tts_start_time = time.time()
        tts_first_byte_time = 0
        
        # Determine encoding based on communicator type
        enc_params = "encoding=mulaw&sample_rate=8000"
        
        from utils.config import DEEPGRAM_VOICE
        tts_url = f"wss://api.deepgram.com/v1/speak?model={DEEPGRAM_VOICE}&{enc_params}"
        headers = {"Authorization": f"Token {DEEPGRAM_API_KEY}"}
        
        async def _stream_on_ws(ws):
            nonlocal tts_first_byte_time
            # Handshake: Send text to speak
            await ws.send_json({"type": "Speak", "text": text})
            await ws.send_json({"type": "Flush"})
            
            async for message in ws:
                if message.type == aiohttp.WSMsgType.BINARY:
                    if tts_first_byte_time == 0:
                        tts_first_byte_time = time.time() - tts_start_time
                    
                    payload_b64 = base64.b64encode(message.data).decode("utf-8")
                    await communicator.send_media(payload_b64)
                elif message.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if data.get("type") == "Flushed":
                        break
                elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                    break

        try:
            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            elif aiohttp_session:
                async with aiohttp_session.ws_connect(tts_url, headers=headers) as ws:
                    await _stream_on_ws(ws)
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(tts_url, headers=headers) as ws:
                        await _stream_on_ws(ws)
            
            self.last_tts_latency = tts_first_byte_time
            self.last_provider = "Deepgram"
            self.last_model = DEEPGRAM_VOICE
            logger.info(f"✅ [Deepgram TTS] Complete. First byte: {tts_first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [Deepgram TTS] Error: {e}")

    async def _elevenlabs_speak(self, text, communicator, aiohttp_session=None, ws_to_use=None):
        """ElevenLabs TTS (Streaming via WebSocket)."""
        if not ELEVENLABS_API_KEY:
            logger.error("❌ ElevenLabs API Key missing!")
            return

        tts_start_time = time.time()
        tts_first_byte_time = 0
        
        url = f"wss://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}/stream-input?model_id=eleven_turbo_v2_5&output_format=pcm_16000"
        
        async def _stream_on_ws(ws):
            nonlocal tts_first_byte_time
            el_resample_state = None
            await ws.send_json({
                "text": " ",
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.8},
                "xi_api_key": ELEVENLABS_API_KEY
            })
            await ws.send_json({"text": text, "try_trigger_generation": True})
            await ws.send_json({"text": ""})
            
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(message.data)
                    if data.get("audio"):
                        if tts_first_byte_time == 0:
                            tts_first_byte_time = time.time() - tts_start_time
                        
                        pcm_16k = base64.b64decode(data["audio"])
                        pcm_8k, el_resample_state = audioop.ratecv(pcm_16k, 2, 1, 16000, 8000, el_resample_state)
                        ulaw_8k = audioop.lin2ulaw(pcm_8k, 2)
                        b64_audio = base64.b64encode(ulaw_8k).decode()
                        
                        await communicator.send_media(b64_audio)
                    
                    if data.get("isFinal"):
                        break
                elif message.type in [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR]:
                    break

        headers = {"xi-api-key": ELEVENLABS_API_KEY}
        try:
            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            elif aiohttp_session:
                async with aiohttp_session.ws_connect(url, headers=headers) as ws:
                    await _stream_on_ws(ws)
            else:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(url, headers=headers) as ws:
                        await _stream_on_ws(ws)
            
            self.last_tts_latency = tts_first_byte_time
            self.last_provider = "ElevenLabs"
            self.last_model = "eleven_turbo_v2_5"
            logger.info(f"🔊 [ElevenLabs] TTS complete. First byte: {tts_first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [ElevenLabs TTS] Error: {e}")
