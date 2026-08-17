import audioop
import asyncio
import logging
import websockets
from typing import AsyncGenerator, Dict, Any
from gnani.stt import GnaniSTTStreamClient, StreamTranscriptEvent, StreamProcessingEvent
from gnani.stt.client import (
    StreamErrorEvent,
    StreamConnectedEvent
)
from gnani.stt.exceptions import StreamConnectionError

logger = logging.getLogger(__name__)

class VachanaSTTStreamClient(GnaniSTTStreamClient):
    def __init__(self, *args, format_type: str = "verbatim", **kwargs):
        super().__init__(*args, **kwargs)
        self.format_type = format_type

    async def connect(self):
        headers = {
            "x-api-key-id": self.api_key,
            "lang_code": self.language_code,
            "x-format": self.format_type,
        }

        try:
            self._ws = await websockets.connect(
                self._ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=10,
            )
        except Exception as exc:
            raise StreamConnectionError(f"Failed to connect to {self._ws_url}: {exc}") from exc

        self._transcripts.clear()
        self._events = asyncio.Queue()
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Wait for the initial "connected" message
        first = await self._events.get()
        if isinstance(first, StreamConnectedEvent):
            self._connected_event = first
            return first
        elif isinstance(first, StreamErrorEvent):
            await self._close_ws()
            raise StreamConnectionError(f"Server error on connect: {first.message}")
        else:
            await self._close_ws()
            raise StreamConnectionError("Unexpected first message from server")


class VachanaSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Vachana"
        # The model setting acts as the x-format option ("verbatim" or "transcribe")
        self.model = model or "verbatim"
        self.api_key = api_key
        self.language = "en-IN"  # Set dynamically by pipeline

        if not self.api_key:
            logger.warning("VachanaSTT initialized without an API key! Transcription will fail.")

    async def transcribe(
        self, audio_generator, encoding: str = "linear16", sample_rate: int = 8000
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [VachanaSTT] API Key missing.")
            yield {"transcript": "[Error: Vachana API Key Missing]", "is_final": True}
            return

        # Ensure format_type is valid
        format_type = self.model if self.model in ["verbatim", "transcribe"] else "verbatim"

        logger.info(f"🎙️ Starting Vachana Realtime STT: {encoding} @ {sample_rate}Hz, lang={self.language}, format={format_type}")

        # Always send 16kHz to Vachana — no sample_rate header is sent in the
        # WS handshake so the server defaults to 16kHz. Twilio delivers mulaw
        # 8kHz; we resample up before forwarding.
        vachana_sample_rate = 16000

        # Initialize stream client
        stream = VachanaSTTStreamClient(
            api_key=self.api_key,
            language_code=self.language,
            sample_rate=vachana_sample_rate,
            format_type=format_type
        )

        try:
            await stream.connect()
            logger.info("🎯 Vachana STT WebSocket Connected")

            async def sender():
                try:
                    buffer = b""
                    _resample_state = None
                    async for raw_chunk in audio_generator:
                        if not raw_chunk:
                            continue

                        # mulaw 8kHz → linear16 8kHz → linear16 16kHz
                        if "mulaw" in encoding:
                            lin16_8k = audioop.ulaw2lin(raw_chunk, 2)
                        else:
                            lin16_8k = raw_chunk

                        if sample_rate != 16000:
                            pcm, _resample_state = audioop.ratecv(
                                lin16_8k, 2, 1, sample_rate, 16000, _resample_state
                            )
                        else:
                            pcm = lin16_8k

                        buffer += pcm

                        # Send in 1024-byte chunks
                        while len(buffer) >= 1024:
                            chunk_to_send = buffer[:1024]
                            buffer = buffer[1024:]
                            await stream.send_audio(chunk_to_send)

                    # Final flush with padding
                    if buffer:
                        padded_chunk = buffer + b"\x00" * (1024 - len(buffer))
                        await stream.send_audio(padded_chunk)

                except Exception as e:
                    logger.error(f"❌ [VachanaSTT] Send error: {e}")
                finally:
                    try:
                        await stream.close()
                    except Exception:
                        pass

            async def receiver():
                try:
                    async for event in stream:
                        if isinstance(event, StreamTranscriptEvent):
                            yield {
                                "transcript": event.text,
                                "is_final": True,
                                "type": "transcript"
                            }
                        elif isinstance(event, StreamProcessingEvent):
                            yield {
                                "type": "processing"
                            }
                except Exception as e:
                    logger.error(f"❌ [VachanaSTT] Receive error: {e}")

            send_task = asyncio.create_task(sender())
            try:
                async for result in receiver():
                    yield result
            finally:
                send_task.cancel()
                try:
                    await stream.close()
                except Exception:
                    pass

        except Exception as e:
            logger.error(f"❌ [VachanaSTT] Connection error: {e}")
            yield {"transcript": f"[Error: {e}]", "is_final": True}
