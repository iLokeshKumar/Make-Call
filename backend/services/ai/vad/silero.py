"""Silero-VAD confirmation gate for the voice pipeline.

Used to suppress false-positive barge-ins.  The existing RMS-energy trigger
in voice_pipeline._barge_in_detector is fast but over-eager on background
noise, breath, and mic plosives.  When RMS crosses threshold we ask Silero
whether the frame actually contains speech; only then do we raise
interrupt_pending + pause TTS.

Design notes:
  * One process-wide model — Silero is small (~2MB) but Torch graph init is
    expensive.  Singleton via SileroVadGate.shared().
  * Sync inference — Silero is fast on CPU (~2-10ms per 32ms frame).  Caller
    runs on the audio hot path, already async, so this blocks the loop for
    one frame at most.
  * Fail-safe OPEN — any exception returns True (speech detected) so we do
    not silently drop legitimate barge-ins.  Logged at WARNING so the issue
    surfaces without breaking the call.

Input format:
  * Silero expects mono PCM16 at 8k or 16k sample rate.
  * The pipeline ships pcm_mulaw@8k over Twilio / EnableX WebRTC.  We decode
    mulaw → PCM16 in-process (audioop is stdlib).  For providers that send
    PCM16 directly we pass through.
"""
from __future__ import annotations

import audioop
import logging
import os
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Silero accepts 512-sample windows at 16k (32ms) or 256-sample at 8k (32ms). We normalise everything to 16k PCM16 to keep the model call simple.
_TARGET_SAMPLE_RATE = 16000
_MIN_PCM16_SAMPLES = 512  # 32ms @ 16kHz


class SileroVadGate:
    """Lazy-loaded Silero-VAD confirmation gate."""

    _shared: Optional["SileroVadGate"] = None
    _lock = threading.Lock()

    def __init__(self, threshold: float = 0.5) -> None:
        self._threshold = threshold
        self._model = None
        self._get_speech_timestamps = None
        self._torch = None

    @classmethod
    def shared(cls) -> "SileroVadGate":
        with cls._lock:
            if cls._shared is None:
                cls._shared = cls()
        return cls._shared

    def _ensure_loaded(self) -> bool:
        """Load model + torch on first call.  Returns False on failure."""
        if self._model is not None:
            return True
        try:
            import torch
            from silero_vad import load_silero_vad  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            logger.warning("[silero_vad] import failed: %s", exc)
            return False

        try:
            custom_path = os.getenv("SILERO_VAD_MODEL_PATH")
            if custom_path and os.path.isfile(custom_path):
                # Load from a pre-downloaded JIT model file for offline installs.
                self._model = torch.jit.load(custom_path)
                self._model.eval()
            else:
                from silero_vad import load_silero_vad
                # Silero 6.x returns a compiled torch model; onnx=True is smaller but adds onnxruntime dep.  Stick with Torch backend.
                self._model = load_silero_vad()
            self._torch = torch
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("[silero_vad] model load failed: %s", exc)
            self._model = None
            return False

    def is_speech(self, pcm16: bytes, sample_rate: int = _TARGET_SAMPLE_RATE) -> bool:
        """Return True if the frame likely contains human speech.

        Fails OPEN (returns True) on any loading / inference error so the
        pipeline never silently drops real barge-ins because the VAD is
        misbehaving.
        """
        if not pcm16:
            return False

        if not self._ensure_loaded():
            return True

        try:
            torch = self._torch
            # Build a float32 tensor in [-1, 1].  Silero expects shape (N,).
            if sample_rate != _TARGET_SAMPLE_RATE:
                pcm16, _ = audioop.ratecv(pcm16, 2, 1, sample_rate, _TARGET_SAMPLE_RATE, None)

            if len(pcm16) < _MIN_PCM16_SAMPLES * 2:
                # Not enough samples for one 32ms window → inconclusive. Default to False (no speech) so short blips don't trigger.
                return False

            import array
            a = array.array("h")
            a.frombytes(pcm16[: _MIN_PCM16_SAMPLES * 2])
            tensor = torch.tensor(a, dtype=torch.float32) / 32768.0

            with torch.no_grad():
                score = float(self._model(tensor, _TARGET_SAMPLE_RATE).item())
        except Exception as exc:  # noqa: BLE001
            logger.warning("[silero_vad] inference failed: %s — failing open", exc)
            return True

        return score >= self._threshold


def _mulaw_to_pcm16(mulaw: bytes) -> bytes:
    """Decode 8-bit mulaw to 16-bit little-endian PCM."""
    if not mulaw:
        return b""
    try:
        return audioop.ulaw2lin(mulaw, 2)
    except Exception as exc:  # noqa: BLE001
        logger.debug("[silero_vad] mulaw decode failed: %s", exc)
        return b""


def silero_confirms_speech(
    audio_bytes: bytes,
    encoding: str,
    sample_rate: int,
    gate: Optional[SileroVadGate] = None,
) -> bool:
    """Confirm a suspected barge-in frame contains real speech.

    Wraps Silero with encoding-aware decoding.  Callers pass the raw audio
    chunk + its original encoding/sample_rate; we decode + resample as
    needed.  Returns True on real speech OR on any error (fail-safe open).
    """
    gate = gate or SileroVadGate.shared()
    enc = (encoding or "").lower()

    if enc in {"mulaw", "pcm_mulaw", "ulaw"}:
        pcm16 = _mulaw_to_pcm16(audio_bytes)
        src_rate = sample_rate or 8000
    elif enc in {"linear16", "pcm16", "pcm_s16le", "pcm"}:
        pcm16 = audio_bytes
        src_rate = sample_rate or 16000
    else:
        logger.debug("[silero_vad] unknown encoding=%r — failing open", encoding)
        return True

    return gate.is_speech(pcm16, sample_rate=src_rate)
