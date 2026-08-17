import audioop
import base64
import logging
import os
import time

import aiohttp

logger = logging.getLogger(__name__)


class AzureTTS:
    """Azure Cognitive Services TTS — streams mulaw to Twilio communicator.

    Required env vars (or company settings):
        AZURE_SPEECH_KEY    — subscription key
        AZURE_SPEECH_REGION — e.g. "centralindia"
    Optional:
        AZURE_SPEECH_API_KEY — alias for AZURE_SPEECH_KEY
        AZURE_API_KEY        — fallback alias for AZURE_SPEECH_KEY
    """

    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Azure"
        self.api_key = (
            api_key
            or os.getenv("AZURE_SPEECH_API_KEY")
            or os.getenv("AZURE_SPEECH_KEY")
            or os.getenv("AZURE_API_KEY")
        )
        self.region = os.getenv("AZURE_SPEECH_REGION", "centralindia")
        self.voice_name = voice_id or "en-US-JennyNeural"
        self.model = model or "azure-tts"
        self.last_latency = 0.0

        if not self.api_key:
            logger.warning("AzureTTS: no API key — synthesis will fail.")

    async def speak(
        self,
        text: str,
        communicator,
        ws_to_use=None,
        context_id=None,
        is_final=True,
        **kwargs,
    ):
        if not self.api_key:
            logger.error("❌ [AzureTTS] API key missing.")
            return

        start_time = time.time()
        first_byte_time = 0.0

        ssml = (
            f'<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">'
            f'<voice name="{self.voice_name}">{text}</voice>'
            f"</speak>"
        )

        url = getattr(self, "base_url", None) or f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1"
        headers = {
            "Ocp-Apim-Subscription-Key": self.api_key or "",
            "Content-Type": "application/ssml+xml",
            # 16kHz PCM — we resample to 8k mulaw for Twilio
            "X-Microsoft-OutputFormat": "raw-16khz-16bit-mono-pcm",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, data=ssml) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        logger.error("❌ [AzureTTS] HTTP %s: %s", resp.status, err)
                        return

                    resample_state = None
                    leftover = b""
                    async for chunk in resp.content.iter_chunked(4096):
                        if not chunk:
                            continue
                        if first_byte_time == 0.0:
                            first_byte_time = time.time() - start_time
                        # s16le = 2 bytes/sample; ensure even-length input for audioop
                        chunk = leftover + chunk
                        if len(chunk) % 2:
                            leftover = chunk[-1:]
                            chunk = chunk[:-1]
                        else:
                            leftover = b""
                        if not chunk:
                            continue
                        # 16kHz PCM s16le → 8kHz → mulaw
                        pcm_8k, resample_state = audioop.ratecv(chunk, 2, 1, 16000, 8000, resample_state)
                        mulaw = audioop.lin2ulaw(pcm_8k, 2)
                        await communicator.send_media(base64.b64encode(mulaw).decode())

            self.last_latency = first_byte_time
            logger.info("✅ [AzureTTS] Done. First byte: %.3fs", first_byte_time)
        except Exception as exc:
            logger.error("❌ [AzureTTS] Error: %s", exc)
