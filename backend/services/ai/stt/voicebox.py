import audioop
import io
import logging
import wave
import aiohttp
from typing import AsyncGenerator, Dict, Any

logger = logging.getLogger(__name__)

_BASE_URL = "http://127.0.0.1:17493"
_CLIENT_HEADER = {"X-Voicebox-Client-Id": "rio-crm"}

_STT_RATE = 16000
_CHUNK_THRESHOLD = _STT_RATE * 2 * 2  # ~2 seconds of 16kHz s16le


def _to_wav(pcm_16k: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(_STT_RATE)
        wf.writeframes(pcm_16k)
    return buf.getvalue()


class VoiceboxSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Voicebox"

    async def transcribe(
        self, audio_generator, encoding: str = "pcm_mulaw", sample_rate: int = 8000
    ) -> AsyncGenerator[Dict[str, Any], None]:
        buffer = b""
        resample_state = None

        async with aiohttp.ClientSession() as session:
            try:
                async for chunk in audio_generator:
                    if not chunk:
                        continue

                    pcm = audioop.ulaw2lin(chunk, 2) if "mulaw" in encoding else chunk

                    if sample_rate != _STT_RATE:
                        pcm, resample_state = audioop.ratecv(
                            pcm, 2, 1, sample_rate, _STT_RATE, resample_state
                        )

                    buffer += pcm

                    if len(buffer) >= _CHUNK_THRESHOLD:
                        async for result in self._send(session, buffer):
                            yield result
                        buffer = b""

                if buffer:
                    async for result in self._send(session, buffer):
                        yield result

            except Exception as e:
                logger.error("❌ [VoiceboxSTT] Error: %s", e)

    async def _send(self, session: aiohttp.ClientSession, pcm: bytes):
        wav = _to_wav(pcm)
        data = aiohttp.FormData()
        data.add_field("file", wav, filename="audio.wav", content_type="audio/wav")

        try:
            async with session.post(
                f"{_BASE_URL}/transcribe",
                data=data,
                headers=_CLIENT_HEADER,
            ) as resp:
                if resp.status == 200:
                    res = await resp.json()
                    transcript = (res.get("transcript") or res.get("text") or "").strip()
                    if transcript:
                        logger.info("🎙️ [VoiceboxSTT] %s", transcript)
                        yield {"transcript": transcript, "is_final": True, "type": "transcript"}
                else:
                    body = await resp.text()
                    logger.error("❌ [VoiceboxSTT] %s: %s", resp.status, body)
        except aiohttp.ClientConnectorError:
            logger.error("❌ [VoiceboxSTT] Cannot connect — is Voicebox running at %s?", _BASE_URL)
