import asyncio
import audioop
import base64
import logging
import time

import boto3
from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger(__name__)

# Amazon Polly TTS
# OutputFormat: pcm (16-bit LINEAR PCM) at 8kHz → direct lin2ulaw → Twilio mulaw
# Engine: neural (better quality) or standard
# Voices: Kajal (en-IN), Aditi (hi-IN), Joanna/Matthew (en-US)
# Auth: AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY + AWS_DEFAULT_REGION env vars


class PollyTTS:
    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "Polly"
        self.voice_id = voice_id or "Kajal"
        self.engine = model or "neural"
        self.model = self.engine  # pipeline expects .model attribute
        self.last_latency = 0.0

        # boto3 uses AWS env vars / IAM role automatically; api_key unused
        try:
            self.client = boto3.client("polly")
        except Exception as exc:
            logger.error("❌ [PollyTTS] Failed to create boto3 client: %s", exc)
            self.client = None

        if not self.client:
            logger.warning("PollyTTS client not initialized — calls will fail.")

    def _synthesize_sync(self, text: str):
        """Blocking boto3 call — run inside run_in_executor."""
        return self.client.synthesize_speech(
            Text=text,
            OutputFormat="pcm",
            SampleRate="8000",
            VoiceId=self.voice_id,
            Engine=self.engine,
        )

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None,
                    aiohttp_session=None, is_final=True, **kwargs):
        if not self.client:
            logger.error("❌ [PollyTTS] Client not available.")
            return
        if not text or not text.strip():
            return

        start = time.time()
        first_byte_time = 0.0
        loop = asyncio.get_event_loop()

        try:
            response = await loop.run_in_executor(None, self._synthesize_sync, text)
        except (BotoCoreError, ClientError) as exc:
            logger.error("❌ [PollyTTS] Synthesis error: %s", exc)
            return
        except Exception as exc:
            logger.error("❌ [PollyTTS] Unexpected error: %s", exc)
            return

        audio_stream = response["AudioStream"]
        # 640 bytes = 40ms of 16-bit PCM mono at 8kHz
        _CHUNK = 640

        try:
            while True:
                chunk = await loop.run_in_executor(None, audio_stream.read, _CHUNK)
                if not chunk:
                    break
                if first_byte_time == 0.0:
                    first_byte_time = time.time() - start
                    self.last_latency = first_byte_time
                mulaw = audioop.lin2ulaw(chunk, 2)
                await communicator.send_media(base64.b64encode(mulaw).decode())
        except Exception as exc:
            logger.error("❌ [PollyTTS] Stream error: %s", exc)
        finally:
            try:
                audio_stream.close()
            except Exception:
                pass

        logger.info("[PollyTTS] Done — voice=%s engine=%s first_byte=%.3fs",
                    self.voice_id, self.engine, first_byte_time)