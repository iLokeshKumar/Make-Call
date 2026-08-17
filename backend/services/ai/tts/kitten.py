import asyncio
import audioop
import base64
import logging
import os
import re
import time

import numpy as np

logger = logging.getLogger(__name__)

_model_instance = None
_model_lock = asyncio.Lock()


def _load_model_sync(model_name: str):
    from kittentts import KittenTTS
    return KittenTTS(model_name)


def _generate_sync(model, text: str, voice: str, speed: float) -> np.ndarray:
    return model.generate(text, voice=voice, speed=speed)


def number_to_words(num: int) -> str:
    if num == 0:
        return "zero"

    units = ["", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
             "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen",
             "seventeen", "eighteen", "nineteen"]
    tens = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]

    words = []

    if num >= 1000:
        words.append(number_to_words(num // 1000) + " thousand")
        num %= 1000

    if num >= 100:
        words.append(units[num // 100] + " hundred")
        num %= 100

    if num >= 20:
        word = tens[num // 10]
        if num % 10:
            word += "-" + units[num % 10]
        words.append(word)
    elif num > 0:
        words.append(units[num])

    return " ".join(words)


def _num_replacer(match):
    num_str = match.group(0)
    try:
        if "." in num_str:
            parts = num_str.split(".")
            integer_part = number_to_words(int(parts[0]))
            fractional_part = " ".join(number_to_words(int(digit)) for digit in parts[1])
            return f"{integer_part} point {fractional_part}"
        else:
            return number_to_words(int(num_str))
    except Exception:
        return num_str


def normalize_tts_text(text: str) -> str:
    if not text:
        return ""
    # Smart quotes
    text = text.replace("‘", "'").replace("’", "'")  # ' '
    text = text.replace("“", '"').replace("”", '"')  # " "
    # All dash / hyphen / minus Unicode variants -> ASCII hyphen-minus (U+002D).
    # Em dash and horizontal bar get a space either side so they sound like a natural pause.
    text = text.replace("‐", "-")   # HYPHEN
    text = text.replace("‑", "-")   # NON-BREAKING HYPHEN
    text = text.replace("‒", "-")   # FIGURE DASH
    text = text.replace("–", "-")   # EN DASH
    text = text.replace("—", ", ")  # EM DASH -> comma (clause pause; avoids standalone hyphen word that confuses phonemizer)
    text = text.replace("―", ", ")  # HORIZONTAL BAR
    text = text.replace("−", "-")   # MINUS SIGN
    text = text.replace("﹘", "-")   # SMALL EM DASH
    text = text.replace("﹣", "-")   # SMALL HYPHEN-MINUS
    text = text.replace("－", "-")   # FULLWIDTH HYPHEN-MINUS
    # Split compound measurements (e.g. "32-inch") so phonemizer word count matches
    text = re.sub(r"(\d+)\s*[-–—‑]\s*([a-zA-Z]+)", r"\1 \2", text)
    text = re.sub(r",\s*,", ", ", text)
    text = re.sub(r"\s+", " ", text).strip()
    # Expand numbers
    text = re.sub(r'\b\d+(\.\d+)?\b', _num_replacer, text)
    return text


class KittenTTS:
    """
    Local CPU TTS via KittenTTS (ONNX, no API key).
    Voices: Bella, Jasper, Luna, Bruno, Rosie, Hugo, Kiki, Leo
    Models: KittenML/kitten-tts-mini-0.8 (80MB), kitten-tts-micro, kitten-tts-nano
    """

    VALID_VOICES = {"Bella", "Jasper", "Luna", "Bruno", "Rosie", "Hugo", "Kiki", "Leo"}

    def __init__(self, api_key: str = None, voice_id: str = None, model: str = None):
        self.provider = "KittenTTS"
        self.model_name = model or os.getenv("KITTENTTS_MODEL", "KittenML/kitten-tts-mini-0.8")
        self.model = self.model_name
        raw_voice = voice_id or os.getenv("KITTENTTS_VOICE", "Jasper")
        self.voice_id = raw_voice if raw_voice in self.VALID_VOICES else "Jasper"
        self.speed = float(os.getenv("KITTENTTS_SPEED", "1.0"))
        self.last_latency = 0.0
        # api_key unused — local model

    async def _get_model(self):
        global _model_instance
        if _model_instance is not None:
            return _model_instance
        async with _model_lock:
            if _model_instance is None:
                logger.info("[KittenTTS] Loading model %s ...", self.model_name)
                loop = asyncio.get_event_loop()
                _model_instance = await loop.run_in_executor(None, _load_model_sync, self.model_name)
                logger.info("[KittenTTS] Model ready.")
        return _model_instance

    async def speak(self, text: str, communicator, ws_to_use=None, context_id=None,
                    aiohttp_session=None, is_final=True, **kwargs):
        if not text or not text.strip():
            return

        normalized_text = normalize_tts_text(text).strip()
        if not normalized_text:
            return

        start = time.time()
        loop = asyncio.get_event_loop()

        try:
            model = await self._get_model()
            audio_float32 = await loop.run_in_executor(
                None, _generate_sync, model, normalized_text, self.voice_id, self.speed
            )
        except Exception as exc:
            logger.error("[KittenTTS] Generation error: %s", exc)
            return

        # float32 [-1, 1] -> int16 PCM
        pcm_int16 = (audio_float32 * 32767).clip(-32768, 32767).astype(np.int16)
        pcm_bytes = pcm_int16.tobytes()

        # Resample 24000 Hz -> 8000 Hz (required for telephony/mulaw)
        resampled, _ = audioop.ratecv(pcm_bytes, 2, 1, 24000, 8000, None)

        # 640 bytes = 40ms of 16-bit PCM mono at 8 kHz
        _CHUNK = 640
        first_chunk = True

        try:
            offset = 0
            while offset < len(resampled):
                chunk = resampled[offset: offset + _CHUNK]
                if not chunk:
                    break
                if first_chunk:
                    self.last_latency = time.time() - start
                    first_chunk = False
                mulaw = audioop.lin2ulaw(chunk, 2)
                await communicator.send_media(base64.b64encode(mulaw).decode())
                offset += _CHUNK
        except Exception as exc:
            logger.error("[KittenTTS] Send error: %s", exc)
            return

        logger.info("[KittenTTS] Done — voice=%s model=%s latency=%.3fs bytes=%d",
                    self.voice_id, self.model_name, self.last_latency, len(resampled))
