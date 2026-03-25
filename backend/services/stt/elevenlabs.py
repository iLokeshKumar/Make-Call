import audioop
import logging
import struct
import aiohttp
from typing import AsyncGenerator, Dict, Any

logger = logging.getLogger(__name__)

# VAD tuning
SPEECH_RMS          = 300   # RMS above this = speech (Twilio barge-in uses 400; slightly lower here)
MIN_SPEECH_FRAMES   = 15    # ~300 ms of speech required before committing (at 20 ms/frame)
SILENCE_TO_COMMIT   = 40    # ~800 ms of post-speech silence triggers transcription
PRE_BUFFER_FRAMES   = 10    # frames of audio kept before speech onset (~200 ms)


def _make_wav(pcm_data: bytes, sample_rate: int = 16000,
              channels: int = 1, sample_width: int = 2) -> bytes:
    """Wrap raw PCM bytes in a minimal WAV container."""
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate,
        sample_rate * channels * sample_width,
        channels * sample_width, sample_width * 8,
        b"data", data_size,
    )
    return header + pcm_data


class ElevenLabsSTT:
    def __init__(self, api_key: str = None, model: str = None):
        self.provider = "ElevenLabs"
        self.model = model or "scribe_v1"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("ElevenLabsSTT initialized without an API key! Transcription will fail.")

    async def _call_api(self, chunks: list, is_mulaw: bool, sample_rate: int) -> str:
        """Convert collected audio chunks to WAV and POST to ElevenLabs Scribe."""
        raw = b"".join(chunks)
        if is_mulaw:
            pcm_8k = audioop.ulaw2lin(raw, 2)
            pcm_data, _ = audioop.ratecv(pcm_8k, 2, 1, sample_rate, 16000, None)
            wav_rate = 16000
        else:
            pcm_data = raw
            wav_rate = sample_rate

        wav_bytes = _make_wav(pcm_data, wav_rate)
        headers = {"xi-api-key": self.api_key}
        form = aiohttp.FormData()
        form.add_field("model_id", self.model)
        form.add_field("file", wav_bytes, filename="audio.wav", content_type="audio/wav")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.elevenlabs.io/v1/speech-to-text",
                    headers=headers, data=form
                ) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return result.get("text", "").strip()
                    else:
                        error = await resp.text()
                        logger.error(f"❌ [ElevenLabsSTT] API Error {resp.status}: {error}")
                        return ""
        except Exception as e:
            logger.error(f"❌ [ElevenLabsSTT] Request error: {e}")
            return ""

    async def transcribe(self, audio_generator, encoding: str = "linear16",
                         sample_rate: int = 8000) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            logger.error("❌ [ElevenLabsSTT] API Key missing!")
            yield {"type": "end_of_turn"}
            return

        is_mulaw = "mulaw" in encoding or "ulaw" in encoding

        pre_buffer: list = []        # rolling audio before speech onset
        utterance: list = []         # audio chunks of the current utterance
        speech_frames = 0            # voiced frames in current utterance
        silence_frames = 0           # consecutive silent frames after speech
        in_speech = False

        async for chunk in audio_generator:
            if not chunk:
                continue

            # Compute RMS on linear PCM
            try:
                pcm = audioop.ulaw2lin(chunk, 2) if is_mulaw else chunk
                rms = audioop.rms(pcm, 2)
            except Exception:
                rms = 0

            if rms >= SPEECH_RMS:
                if not in_speech:
                    # Speech onset — carry the pre-buffer so onset isn't clipped
                    utterance = list(pre_buffer) + [chunk]
                    pre_buffer = []
                    in_speech = True
                    speech_frames = 1
                    silence_frames = 0
                else:
                    utterance.append(chunk)
                    speech_frames += 1
                    silence_frames = 0
            else:
                if in_speech:
                    utterance.append(chunk)
                    silence_frames += 1

                    if silence_frames >= SILENCE_TO_COMMIT:
                        # End of utterance — transcribe if enough real speech
                        if speech_frames >= MIN_SPEECH_FRAMES:
                            logger.info(
                                f"🎙️ [ElevenLabsSTT] Utterance ended "
                                f"({speech_frames} speech frames). Sending to API..."
                            )
                            text = await self._call_api(utterance, is_mulaw, sample_rate)
                            if text:
                                logger.info(f"🎯 [ElevenLabsSTT] Transcript: '{text}'")
                                yield {"transcript": text, "is_final": True, "type": "transcript"}
                                yield {"type": "end_of_turn"}
                        else:
                            logger.debug(
                                f"⚠️ [ElevenLabsSTT] Skipped short segment "
                                f"({speech_frames} frames < {MIN_SPEECH_FRAMES})"
                            )

                        # Reset for next utterance
                        utterance = []
                        speech_frames = 0
                        silence_frames = 0
                        in_speech = False
                else:
                    # Maintain rolling pre-buffer (so speech onset isn't clipped)
                    pre_buffer.append(chunk)
                    if len(pre_buffer) > PRE_BUFFER_FRAMES:
                        pre_buffer.pop(0)

        # Call ends — flush any remaining speech
        if in_speech and speech_frames >= MIN_SPEECH_FRAMES:
            logger.info(f"🎙️ [ElevenLabsSTT] Flushing final utterance ({speech_frames} frames)...")
            text = await self._call_api(utterance, is_mulaw, sample_rate)
            if text:
                logger.info(f"🎯 [ElevenLabsSTT] Final transcript: '{text}'")
                yield {"transcript": text, "is_final": True, "type": "transcript"}

        yield {"type": "end_of_turn"}
