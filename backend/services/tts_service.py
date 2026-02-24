import asyncio
import base64
import logging
import time
import json
import aiohttp
from typing import Optional
from utils.config import (
    async_cartesia_client, CARTESIA_VOICE_ID, 
    SARVAM_API_KEY, ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
    DEEPGRAM_API_KEY
)
from utils.audio import clean_voice_text

logger = logging.getLogger(__name__)

class TTSService:
    def __init__(self):
        self.last_tts_latency = 0

    async def speak(self, text: str, engine_type: str, communicator, cartesia_ws=None):
        """
        Generic speak method that routes to the correct provider.
        """
        text = clean_voice_text(text)
        if not text:
            return

        if engine_type == "mistral-cartesia":
            await self._cartesia_speak(text, communicator, cartesia_ws)
        elif engine_type == "mistral-sarvam":
            await self._sarvam_speak(text, communicator)
        elif engine_type == "mistral-deepgram":
            await self._deepgram_speak(text, communicator)
        elif engine_type == "mistral-elevenlabs":
            await self._elevenlabs_speak(text, communicator)
        else:
            logger.warning(f"⚠️ Unsupported TTS engine: {engine_type}")

    async def _cartesia_speak(self, text, communicator, ws_to_use=None):
        """Streaming TTS from Cartesia using SDK 3.0.0.
        
        In SDK v3, websocket_connect() takes no config args.
        All config (model_id, voice_id, output_format, transcript) must be
        passed as a single dict to ws.send(event_dict).
        Audio is read back via ws.recv_bytes().
        """
        try:
            start_time = time.time()
            tts_first_byte_time = 0

            # Event dict for SDK v3 - all config goes here
            tts_event = {
                "model_id": "sonic-english",
                "voice": {
                    "mode": "id",
                    "id": CARTESIA_VOICE_ID,
                },
                "transcript": text,
                "output_format": {
                    "container": "raw",
                    "encoding": "pcm_mulaw",
                    "sample_rate": 8000,
                },
                "language": "en",
                "add_timestamps": False,
            }

            async def _stream_on_ws(ws):
                nonlocal tts_first_byte_time
                # In SDK v3, send takes a single event dict
                await ws.send(tts_event)
                # Read audio bytes back
                while True:
                    try:
                        audio_chunk = await asyncio.wait_for(ws.recv_bytes(), timeout=5.0)
                        if audio_chunk:
                            if tts_first_byte_time == 0:
                                tts_first_byte_time = time.time() - start_time
                            b64_audio = base64.b64encode(audio_chunk).decode("utf-8")
                            await communicator.send_media(b64_audio)
                    except asyncio.TimeoutError:
                        break  # Done receiving
                    except Exception:
                        break

            if ws_to_use:
                await _stream_on_ws(ws_to_use)
            else:
                # In SDK v3, websocket_connect() takes NO config args
                async with async_cartesia_client.tts.websocket_connect() as new_ws:
                    await _stream_on_ws(new_ws)
            
            self.last_tts_latency = tts_first_byte_time
            logger.info(f"✅ [Cartesia TTS] Complete. First byte: {tts_first_byte_time:.3f}s")
        except Exception as e:
            logger.error(f"❌ [Cartesia TTS] Error: {e}")

    async def _sarvam_speak(self, text, communicator):
        """Sarvam AI TTS."""
        pass

    async def _deepgram_speak(self, text, communicator):
        """Deepgram Aura TTS."""
        url = "https://api.deepgram.com/v1/tts?model=aura-asteria-en"
        headers = {
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"text": text}
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as resp:
                if resp.status == 200:
                    audio_data = await resp.read()
                    b64_audio = base64.b64encode(audio_data).decode("utf-8")
                    await communicator.send_media(b64_audio)
                else:
                    logger.error(f"❌ [Deepgram TTS] Error: {resp.status}")

    async def _elevenlabs_speak(self, text, communicator):
        """ElevenLabs TTS."""
        pass
