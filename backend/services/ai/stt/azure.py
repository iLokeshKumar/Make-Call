import asyncio
import audioop
import logging
import os
from typing import AsyncGenerator, Dict, Any

import azure.cognitiveservices.speech as speechsdk

logger = logging.getLogger(__name__)


class AzureSTT:
    """Azure Cognitive Services STT via Speech SDK (continuous recognition).

    Required env vars (or company settings):
        AZURE_SPEECH_KEY    — subscription key
        AZURE_SPEECH_REGION — e.g. "centralindia"
    """

    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Azure"
        self.api_key = (
            api_key
            or os.getenv("AZURE_SPEECH_API_KEY")
            or os.getenv("AZURE_SPEECH_KEY")
            or os.getenv("AZURE_API_KEY")
        )
        self.region = os.getenv("AZURE_SPEECH_REGION", "centralindia")
        self.language = model or "en-IN"
        self.model = self.language

        if not self.api_key:
            logger.warning("AzureSTT: no API key — transcription will fail.")

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "pcm_mulaw",
        sample_rate: int = 8000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [AzureSTT] API key missing.")
            yield {"transcript": "[Error: Azure Speech key missing]", "is_final": True}
            return

        is_mulaw = "mulaw" in encoding
        loop = asyncio.get_event_loop()
        result_queue: asyncio.Queue = asyncio.Queue()

        # --- Speech config ---
        speech_config = speechsdk.SpeechConfig(
            subscription=self.api_key,
            region=self.region,
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, "10000"
        )
        speech_config.set_property(
            speechsdk.PropertyId.SpeechServiceConnection_EndSilenceTimeoutMs, "1000"
        )

        # Multi-language: always include en-IN alongside the configured language
        languages = [self.language]
        if self.language not in ("en-IN", "en-US", "en-GB"):
            languages.append("en-IN")
        auto_detect = speechsdk.languageconfig.AutoDetectSourceLanguageConfig(
            languages=languages
        )
        logger.info("[AzureSTT/sdk] Languages: %s", languages)

        # --- Push audio stream (16 kHz, 16-bit, mono) ---
        stream_fmt = speechsdk.audio.AudioStreamFormat(
            samples_per_second=16000,
            bits_per_sample=16,
            channels=1,
        )
        push_stream = speechsdk.audio.PushAudioInputStream(stream_fmt)
        audio_config = speechsdk.audio.AudioConfig(stream=push_stream)

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            audio_config=audio_config,
            auto_detect_source_language_config=auto_detect,
        )

        # --- SDK event callbacks (called on SDK threads) ---
        def _on_recognized(evt):
            if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech:
                text = evt.result.text.strip()
                if text:
                    lang = getattr(evt.result, "language", "?")
                    logger.info("[AzureSTT/sdk] ✅ [%s] %r", lang, text)
                    loop.call_soon_threadsafe(
                        result_queue.put_nowait,
                        {"transcript": text, "is_final": True, "type": "transcript"},
                    )
            elif evt.result.reason == speechsdk.ResultReason.NoMatch:
                logger.debug("[AzureSTT/sdk] NoMatch: %s", evt.result.no_match_details)

        def _on_canceled(evt):
            cd = evt.cancellation_details
            if cd.reason == speechsdk.CancellationReason.Error:
                logger.error("[AzureSTT/sdk] Canceled error: %s", cd.error_details)
            else:
                logger.info("[AzureSTT/sdk] Canceled: %s", cd.reason)
            loop.call_soon_threadsafe(result_queue.put_nowait, None)

        def _on_session_stopped(evt):
            logger.info("[AzureSTT/sdk] Session stopped")
            loop.call_soon_threadsafe(result_queue.put_nowait, None)

        recognizer.recognized.connect(_on_recognized)
        recognizer.canceled.connect(_on_canceled)
        recognizer.session_stopped.connect(_on_session_stopped)

        # Start continuous recognition (non-blocking via SDK async future)
        start_future = recognizer.start_continuous_recognition_async()
        await loop.run_in_executor(None, start_future.get)
        logger.info("[AzureSTT/sdk] Continuous recognition started")

        # --- Feeder: convert mulaw→PCM→16kHz and push to SDK stream ---
        async def _feeder():
            resample_state = None
            chunk_count = 0
            try:
                async for chunk in audio_generator:
                    if not chunk:
                        continue
                    pcm = audioop.ulaw2lin(chunk, 2) if is_mulaw else chunk
                    if sample_rate != 16000:
                        pcm, resample_state = audioop.ratecv(
                            pcm, 2, 1, sample_rate, 16000, resample_state
                        )
                    push_stream.write(pcm)
                    chunk_count += 1
                    if chunk_count % 100 == 0:
                        logger.debug("[AzureSTT/sdk] Fed %d chunks", chunk_count)
            except asyncio.CancelledError:
                raise
            finally:
                logger.info("[AzureSTT/sdk] Feeder done — %d chunks", chunk_count)
                push_stream.close()  # signals end-of-audio → SDK fires session_stopped

        feeder_task = asyncio.create_task(_feeder())

        try:
            # Yield transcripts until SDK signals done (None sentinel)
            while True:
                result = await result_queue.get()
                if result is None:
                    break
                yield result
        finally:
            feeder_task.cancel()
            try:
                await feeder_task
            except asyncio.CancelledError:
                pass
            # Graceful stop
            try:
                stop_future = recognizer.stop_continuous_recognition_async()
                await loop.run_in_executor(None, stop_future.get)
            except Exception as exc:
                logger.warning("[AzureSTT/sdk] Stop error: %s", exc)
