import audioop
import base64
import logging
import time
import aiohttp

logger = logging.getLogger(__name__)

_BASE_URL = "http://127.0.0.1:17493"
_CLIENT_HEADER = {"X-Voicebox-Client-Id": "rio-crm"}


def _to_mulaw_8k(pcm: bytes, src_rate: int) -> bytes:
    if src_rate != 8000:
        pcm, _ = audioop.ratecv(pcm, 2, 1, src_rate, 8000, None)
    return audioop.lin2ulaw(pcm, 2)


class VoiceboxTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Voicebox"
        self.profile = voice_id or "default"
        self.last_latency = 0.0

    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        start = time.time()
        first_byte = 0.0

        payload = {"text": text, "profile": self.profile}

        try:
            session = aiohttp_session or aiohttp.ClientSession()
            should_close = aiohttp_session is None
            try:
                async with session.post(
                    f"{_BASE_URL}/generate",
                    json=payload,
                    headers=_CLIENT_HEADER,
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.error("❌ [VoiceboxTTS] %s: %s", resp.status, body)
                        return

                    content_type = resp.headers.get("Content-Type", "")
                    raw = await resp.read()

                    if not raw:
                        logger.warning("⚠️ [VoiceboxTTS] Empty response from /generate")
                        return

                    first_byte = time.time() - start

                    # Voicebox returns PCM WAV — strip 44-byte header if present
                    if raw[:4] == b"RIFF":
                        src_rate = int.from_bytes(raw[24:28], "little")
                        pcm = raw[44:]
                    else:
                        src_rate = 22050  # fallback assumption
                        pcm = raw

                    mulaw = _to_mulaw_8k(pcm, src_rate)
                    await communicator.send_media(base64.b64encode(mulaw).decode())
            finally:
                if should_close:
                    await session.close()

        except aiohttp.ClientConnectorError:
            logger.error("❌ [VoiceboxTTS] Cannot connect — is Voicebox running at %s?", _BASE_URL)
        except Exception as e:
            logger.error("❌ [VoiceboxTTS] Error: %s", e)

        self.last_latency = first_byte
        logger.info("✅ [VoiceboxTTS] Done. First byte: %.3fs", first_byte)
