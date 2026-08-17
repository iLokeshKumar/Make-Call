import asyncio
import io
import logging
import wave
from typing import Any, AsyncGenerator, Dict

import audioop
from groq import Groq

logger = logging.getLogger(__name__)

# Target 16kHz mono 16-bit PCM.
TARGET_SAMPLE_RATE = 16000
TARGET_SAMPLE_WIDTH = 2

# VAD + utterance-framing parameters.
VAD_FRAME_MS = 20
VAD_FRAME_BYTES = int(TARGET_SAMPLE_RATE * TARGET_SAMPLE_WIDTH * VAD_FRAME_MS / 1000)  # 640
VAD_RMS_THRESHOLD = 500          # RMS above this = voiced. Tune per mic/env.
SILENCE_TIMEOUT_MS = 600         # trailing silence that ends an utterance
MIN_UTTERANCE_MS = 300           # ignore blips shorter than this
MAX_UTTERANCE_MS = 6000          # force a final even without a silence gap


class GroqSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "Groq"
        self.model = "whisper-large-v3-turbo"
        # model param repurposed as language code (e.g. "hi", "ta", "auto")
        self.language = (model or "auto") if model and not model.startswith("whisper") else "auto"
        if model and model.startswith("whisper"):
            self.model = model
        self.api_key = api_key
        self.client = Groq(api_key=self.api_key) if self.api_key else None

        if not self.api_key:
            logger.warning("GroqSTT initialized without an API key! Transcription will fail.")

    @staticmethod
    def _pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int = TARGET_SAMPLE_RATE) -> bytes:
        """Encode mono 16-bit PCM into a WAV byte buffer."""
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(TARGET_SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm_bytes)
        return buf.getvalue()

    async def _transcribe_pcm(self, pcm_16k: bytes) -> str:
        if not self.client or not pcm_16k:
            return ""

        wav_bytes = self._pcm_to_wav_bytes(pcm_16k)
        file_obj = ("audio.wav", wav_bytes)

        def _call() -> Any:
            kwargs: dict = dict(model=self.model, file=file_obj, response_format="verbose_json")
            lang = getattr(self, "language", "auto")
            if lang and lang not in ("auto", ""):
                kwargs["language"] = lang
            return self.client.audio.transcriptions.create(**kwargs)

        result = await asyncio.to_thread(_call)
        text = getattr(result, "text", None)
        if text is None and isinstance(result, dict):
            text = result.get("text")
        return (text or "").strip()

    def _convert_to_pcm_16k(
        self,
        chunk: bytes,
        encoding: str,
        sample_rate: int,
        resample_state,
    ):
        """Normalize arbitrary incoming audio into 16kHz 16-bit mono PCM."""
        enc = encoding.lower()
        if "mulaw" in enc:
            linear = audioop.ulaw2lin(chunk, TARGET_SAMPLE_WIDTH)
            if sample_rate != TARGET_SAMPLE_RATE:
                linear, resample_state = audioop.ratecv(
                    linear, TARGET_SAMPLE_WIDTH, 1, sample_rate, TARGET_SAMPLE_RATE, resample_state
                )
            return linear, resample_state
        if enc == "linear16" and sample_rate == TARGET_SAMPLE_RATE:
            return chunk, resample_state
        # Generic fallback: treat as linear16 at the declared sample rate.
        linear, resample_state = audioop.ratecv(
            chunk, TARGET_SAMPLE_WIDTH, 1, sample_rate, TARGET_SAMPLE_RATE, resample_state
        )
        return linear, resample_state

    async def transcribe(
        self,
        audio_generator,
        encoding: str = "linear16",
        sample_rate: int = 8000,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Groq STT with VAD-based utterance framing.

        Incoming audio is normalized to 16kHz 16-bit mono PCM, sliced into 20ms
        frames, and accumulated while voiced. An utterance ends after
        SILENCE_TIMEOUT_MS of trailing silence (or MAX_UTTERANCE_MS as a hard
        cap). Only complete utterances are transcribed and yielded as FINAL,
        so the pipeline's turn-taking logic no longer sees a stream of fake
        finals every 1.2s.
        """
        if not self.client:
            logger.error("❌ [GroqSTT] Client not initialized (missing API key).")
            return

        pcm_buffer = bytearray()            # holds unframed PCM from the source
        utterance_buffer = bytearray()      # holds the current in-progress utterance
        resample_state = None
        voiced_ms = 0
        silence_ms = 0

        async def flush_utterance():
            """Transcribe the current utterance buffer and yield a FINAL event."""
            nonlocal utterance_buffer, voiced_ms, silence_ms
            audio = bytes(utterance_buffer)
            utterance_buffer = bytearray()
            voiced_ms = 0
            silence_ms = 0
            text = await self._transcribe_pcm(audio)
            return text

        try:
            async for chunk in audio_generator:
                if not chunk:
                    continue

                normalized, resample_state = self._convert_to_pcm_16k(
                    chunk, encoding, sample_rate, resample_state
                )
                pcm_buffer.extend(normalized)

                while len(pcm_buffer) >= VAD_FRAME_BYTES:
                    frame = bytes(pcm_buffer[:VAD_FRAME_BYTES])
                    del pcm_buffer[:VAD_FRAME_BYTES]

                    rms = audioop.rms(frame, TARGET_SAMPLE_WIDTH)
                    is_voiced = rms > VAD_RMS_THRESHOLD

                    if is_voiced:
                        utterance_buffer.extend(frame)
                        silence_ms = 0
                        voiced_ms += VAD_FRAME_MS
                    elif voiced_ms > 0:
                        # Trailing silence inside or just after speech — keep it so Whisper gets natural boundaries.
                        utterance_buffer.extend(frame)
                        silence_ms += VAD_FRAME_MS
                    # else: leading silence before any speech → drop the frame.

                    # Finalize when trailing silence is long enough, or hard cap.
                    finalize_by_silence = (
                        voiced_ms >= MIN_UTTERANCE_MS and silence_ms >= SILENCE_TIMEOUT_MS
                    )
                    finalize_by_cap = voiced_ms >= MAX_UTTERANCE_MS

                    if finalize_by_silence or finalize_by_cap:
                        text = await flush_utterance()
                        if text:
                            yield {"transcript": text, "is_final": True, "type": "transcript"}
                    elif voiced_ms > 0 and voiced_ms < MIN_UTTERANCE_MS and silence_ms >= SILENCE_TIMEOUT_MS:
                        # Too-short blip followed by silence. Discard, don't transcribe.
                        utterance_buffer.clear()
                        voiced_ms = 0
                        silence_ms = 0

            # Stream ended. Flush any remaining utterance if it's long enough.
            if voiced_ms >= MIN_UTTERANCE_MS and utterance_buffer:
                text = await flush_utterance()
                if text:
                    yield {"transcript": text, "is_final": True, "type": "transcript"}

        except Exception as exc:
            logger.error("❌ [GroqSTT] Transcription error: %s", exc)
