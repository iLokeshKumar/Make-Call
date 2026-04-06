import audioop
import base64
import io
import json
import logging
import struct
import time
import wave
import aiohttp
from utils import settings_cache

logger = logging.getLogger(__name__)

# WAV header is always 44 bytes for standard PCM WAV
_WAV_HEADER_SIZE = 44


def _strip_wav_header(data: bytes) -> bytes:
    """Strip 44-byte standard PCM WAV header from audio data."""
    if len(data) > _WAV_HEADER_SIZE and data[:4] == b"RIFF":
        return data[_WAV_HEADER_SIZE:]
    return data


def _resample_to_mulaw_8k(pcm_data: bytes, src_rate: int) -> bytes:
    """
    Resample PCM s16le from src_rate → 8000 Hz, then encode to mulaw.
    Uses audioop for zero-dependency resampling.
    """
    if src_rate != 8000:
        pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, src_rate, 8000, None)
    return audioop.lin2ulaw(pcm_data, 2)


class SarvamTTS:
    """
    Sarvam TTS using the persistent WebSocket endpoint.
    Endpoint: wss://api.sarvam.ai/text-to-speech/ws

    Protocol:
      1. On connect → send JSON config frame.
      2. Per sentence → send {"text": "...", "flush": true}.
      3. Server streams back WAV audio chunks — strip header, resample → mulaw 8kHz, forward.

    Falls back to HTTP streaming if the WebSocket connection fails.
    """
    WS_URL = "wss://api.sarvam.ai/text-to-speech/ws"
    HTTP_URL = "https://api.sarvam.ai/text-to-speech/stream"

    # Sarvam WS does NOT support 8kHz; lowest supported is 16000.
    # We receive at 22050 and resample down ourselves.
    WS_SAMPLE_RATE = 22050

    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None, language: str = "en-IN"):
        self.provider = "Sarvam"
        self.model = model or "bulbul:v3"
        self.api_key = api_key
        self.speaker = voice_id or "ritu"
        self.target_language_code = language or "en-IN"
        self.last_latency = 0.0

        if not self.api_key:
            logger.warning("SarvamTTS initialized without an API key! Streams will fail.")

    # Public speak() — called by _speaker_loop per sentence
    async def speak(self, text: str, communicator, ws_to_use=None, aiohttp_session=None, **kwargs):
        if not self.api_key:
            logger.error("❌ [SarvamTTS] API Key missing!")
            return

        if ws_to_use:
            logger.info(f"[SarvamTTS] Using WebSocket for: '{text[:40]}...'")
            streamed = await self._speak_ws(text, communicator, ws_to_use)
            if streamed:
                return
            logger.warning("⚠️ [SarvamTTS] WebSocket returned no audio; falling back to REST.")

        logger.info(f"[SarvamTTS] Using REST API for: '{text[:40]}...'")
        await self._speak_http(text, communicator, aiohttp_session)

    # WebSocket path
    async def _speak_ws(self, text: str, communicator, ws):
        """Send one sentence over the already-open persistent WebSocket."""
        start = time.time()
        first_byte = 0.0
        audio_sent = False
        header_stripped = False
        leftover = b""  # partial PCM carry-over for resampling alignment

        try:
            # Send text request
            msg = json.dumps({
                "text": text,
                "flush": True,   # tell server to finalize/flush this request
            })
            logger.debug(f"📤 [SarvamTTS WS] → {msg[:80]}")
            await ws.send_str(msg)

            async for raw_msg in ws:
                if raw_msg.type == aiohttp.WSMsgType.BINARY:
                    chunk = raw_msg.data

                    # Strip WAV header from first chunk only
                    if not header_stripped:
                        chunk = _strip_wav_header(chunk)
                        header_stripped = True

                    if not chunk:
                        continue

                    chunk = leftover + chunk
                    # Align to 2-byte sample boundary
                    if len(chunk) % 2 != 0:
                        leftover = chunk[-1:]
                        chunk = chunk[:-1]
                    else:
                        leftover = b""

                    if chunk:
                        if first_byte == 0.0:
                            first_byte = time.time() - start
                            logger.info(f"⚡ [SarvamTTS WS] First byte: {first_byte:.3f}s")

                        audio_sent = True

                        mulaw = _resample_to_mulaw_8k(chunk, self.WS_SAMPLE_RATE)
                        await communicator.send_media(base64.b64encode(mulaw).decode("utf-8"))

                elif raw_msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(raw_msg.data)
                    logger.debug(f"📥 [SarvamTTS WS] ← {raw_msg.data[:120]}")

                    # Server signals that this utterance is done
                    if data.get("done") or data.get("status") == "done":
                        logger.info(f"✅ [SarvamTTS WS] Utterance done in {time.time()-start:.3f}s")
                        break

                elif raw_msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                    logger.warning("⚠️ [SarvamTTS WS] Connection closed/error mid-stream.")
                    break

                if not audio_sent and (time.time() - start) > 3:
                    logger.warning("⚠️ [SarvamTTS WS] No audio chunks received after 3s; aborting websocket stream.")
                    break

        except Exception as e:
            logger.error(f"❌ [SarvamTTS WS] Error: {e}")

        self.last_latency = first_byte
        return audio_sent

    # HTTP fallback path (original implementation)
    async def _speak_http(self, text: str, communicator, aiohttp_session=None):
        """Original HTTP streaming fallback."""
        start = time.time()
        first_byte = 0.0

        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json"
        }
        payload = {
            "text": text,
            "target_language_code": self.target_language_code,
            "speaker": self.speaker,
            "model": self.model,
            "pace": 1.1,
            "speech_sample_rate": 8000,
            "output_audio_codec": "mulaw",
            "enable_preprocessing": True
        }

        try:
            session = aiohttp_session or aiohttp.ClientSession()
            should_close = aiohttp_session is None
            try:
                async with session.post(self.HTTP_URL, headers=headers, json=payload) as resp:
                    async for chunk in resp.content.iter_any():
                        if chunk:
                            if first_byte == 0.0:
                                first_byte = time.time() - start
                            await communicator.send_media(base64.b64encode(chunk).decode("utf-8"))
            finally:
                if should_close:
                    await session.close()

            self.last_latency = first_byte
            logger.info(f"✅ [SarvamTTS HTTP] Done. First byte: {first_byte:.3f}s")
        except Exception as e:
            logger.error(f"❌ [SarvamTTS HTTP] Error: {e}")

    # Helper: build the WS connect config frame (sent once after connect)
    def ws_config_frame(self, model: str, speaker: str) -> str:
        """Returns the JSON string to send immediately after WS handshake."""
        return json.dumps({
            "model": model,
            "speaker": speaker,
            "target_language_code": self.target_language_code,
            "speech_sample_rate": self.WS_SAMPLE_RATE,
            "pace": 1.1,
            "enable_preprocessing": True,
        })

    @classmethod
    def ws_config_frame_static(cls, model: str, speaker: str, language: str = "en-IN") -> str:
        """Static version for callers that don't have an instance."""
        return json.dumps({
            "model": model,
            "speaker": speaker,
            "target_language_code": language,
            "speech_sample_rate": cls.WS_SAMPLE_RATE,
            "pace": 1.1,
            "enable_preprocessing": True,
        })
