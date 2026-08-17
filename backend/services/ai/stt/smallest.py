import asyncio
import audioop
import json
import logging
import os
from typing import AsyncGenerator, Dict, Any, Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)


class SmallestSTT:
    def __init__(self, api_key: str = None, model: str = None, language: str = "en"):
        self.provider = "Smallest"
        self.model = model or "pulse"
        self.language = language
        self.api_key = api_key or os.getenv("SMALLEST_API_KEY")

        if not self.api_key:
            logger.warning("SmallestSTT initialized without an API key! Transcription will fail.")

        params = {
            "language": self.language,
            "encoding": "linear16",
            "sample_rate": "16000",
            "word_timestamps": "true",
        }
        base_url = "wss://api.smallest.ai/waves/v1/pulse/get_text"
        self.ws_url = f"{base_url}?{urlencode(params)}"

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "linear16",
        sample_rate: int = 16000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ No API key available for SmallestSTT")
            return

        headers = {"Authorization": f"Bearer {self.api_key}"}
        queue: asyncio.Queue[Optional[Dict[str, Any]]] = asyncio.Queue()

        async def sender(ws):
            try:
                async for chunk in audio_generator:
                    if chunk and isinstance(chunk, bytes):
                        try:
                            linear16 = audioop.ulaw2lin(chunk, 2)
                            resampled, _ = audioop.ratecv(linear16, 2, 1, 8000, 16000, None)
                        except Exception:
                            resampled = chunk
                        await ws.send_bytes(resampled)
                await ws.send_json({"type": "CloseStream"})
                logger.debug("📨 Sent close signal to Smallest STT")
            except Exception as exc:
                logger.error(f"❌ [SmallestSTT] Send error: {exc}")
            finally:
                await queue.put(None)

        async def receiver(ws):
            try:
                async for message in ws:
                    try:
                        if message.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(message.data)

                            if "transcript" in data:
                                transcript = data.get("transcript", "").strip()
                                is_final = data.get("is_final", False)
                                if transcript:
                                    await queue.put(
                                        {
                                            "transcript": transcript,
                                            "is_final": is_final,
                                            "type": "transcript",
                                            "provider": self.provider,
                                            "model": self.model,
                                        }
                                    )
                            if data.get("type") == "end_of_stream":
                                await queue.put({"type": "end_of_turn"})
                                break
                    except json.JSONDecodeError as e:
                        logger.warning(f"⚠️ [SmallestSTT] Failed to parse message: {e}")
            except Exception as exc:
                logger.error(f"❌ [SmallestSTT] Receive error: {exc}")
            finally:
                await queue.put(None)

        try:
            async with aiohttp.ClientSession() as session:
                async with session.ws_connect(self.ws_url, headers=headers) as ws:
                    logger.info("🟢 Connected to Smallest STT WebSocket")
                    sender_task = asyncio.create_task(sender(ws))
                    receiver_task = asyncio.create_task(receiver(ws))
                    try:
                        while True:
                            item = await queue.get()
                            if item is None:
                                break
                            yield item
                            if item.get("type") == "end_of_turn":
                                break
                    finally:
                        sender_task.cancel()
                        receiver_task.cancel()
        except aiohttp.ClientConnectionError as e:
            logger.error(f"❌ [SmallestSTT] WebSocket connection closed: {e}")
        except Exception as e:
            logger.error(f"❌ [SmallestSTT] Unexpected error: {e}")
