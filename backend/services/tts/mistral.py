import json
import logging
import os
import time
import aiohttp
from typing import AsyncGenerator, Optional

logger = logging.getLogger(__name__)

class MistralTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Mistral"
        self.model = model or "mistral-tts"
        self.api_key = api_key or os.getenv("MISTRAL_API_KEY")
        self.voice_id = voice_id or "mistral-7b-instruct"  # Default voice/model for Mistral
        self.last_latency = 0

        if not self.api_key:
            logger.warning("MistralTTS initialized without an API key! Streams will fail.")

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None, **kwargs):
        """Generate speech using Mistral's TTS API."""
        if not self.api_key:
            logger.error("❌ No API key available for MistralTTS")
            return

        try:
            start_time = time.time()
            first_byte_time = 0

            # Mistral TTS API endpoint (assuming REST API for now)
            # Note: This may need adjustment based on actual Mistral TTS API
            url = "https://api.mistral.ai/v1/audio/speech"  # Placeholder - adjust based on actual API

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }

            payload = {
                "model": self.model,
                "input": text,
                "voice": self.voice_id,
                "response_format": "pcm",  # Raw PCM audio
                "speed": 1.0
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        logger.error(f"❌ [MistralTTS] API error {response.status}: {error_text}")
                        return

                    if not first_byte_time:
                        first_byte_time = time.time()
                        self.last_latency = first_byte_time - start_time

                    # Stream the audio response
                    async for chunk in response.content.iter_chunked(4096):
                        if chunk:
                            yield chunk

        except aiohttp.ClientError as e:
            logger.error(f"❌ [MistralTTS] HTTP error: {e}")
        except Exception as e:
            logger.error(f"❌ [MistralTTS] Unexpected error: {e}")

    async def get_voices(self) -> list:
        """Get available voices from Mistral (placeholder - implement if API supports)."""
        # Mistral may not have a voices endpoint, so return known voices
        return [
            {"id": "mistral-7b-instruct", "name": "Mistral 7B", "language": "en"},
            # Add more voices as they become available
        ]
