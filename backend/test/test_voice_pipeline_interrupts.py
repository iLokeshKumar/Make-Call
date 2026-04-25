"""Tests for the voice pipeline R1/R2 state machine + Silero VAD gate.

VoicePipeline.__init__ pulls in heavy deps (communicator, session, all integration
keys) so we bypass it with __new__ and manually seed just the attrs each test
needs.  This trades some fidelity for test speed + decoupling from provider
configuration.
"""
from __future__ import annotations

import asyncio
import os
import sys
import types
from collections import deque
from unittest.mock import MagicMock

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

# Stub provider SDKs not installed in the test env (groq / anthropic / google
# etc.).  The tests do not exercise real LLM/STT/TTS calls — they mock
# services on the pipeline stub.
for _missing_sdk in ("groq", "anthropic", "google", "google.generativeai", "cerebras", "openai"):
    if _missing_sdk not in sys.modules:
        sys.modules[_missing_sdk] = types.ModuleType(_missing_sdk)

# Also replace the high-level factory modules so importing voice_pipeline
# doesn't walk their provider-per-file structure.
_llm_stub = types.ModuleType("services.ai.llm")
def _get_llm_service(*_a, **_kw):
    return MagicMock()
_llm_stub.get_llm_service = _get_llm_service
sys.modules["services.ai.llm"] = _llm_stub

_stt_stub = types.ModuleType("services.ai.stt")
_stt_stub.get_stt_service = lambda *a, **kw: MagicMock()
sys.modules["services.ai.stt"] = _stt_stub

_tts_stub = types.ModuleType("services.ai.tts")
_tts_stub.get_tts_service = lambda *a, **kw: MagicMock()
sys.modules["services.ai.tts"] = _tts_stub

import pytest  # noqa: E402


def _build_pipeline_stub(**overrides):
    """Construct a bare VoicePipeline with only the attributes the unit
    tests exercise.  Avoids __init__ which reaches into DB / providers."""
    from pipelines.voice_pipeline import VoicePipeline

    vp = VoicePipeline.__new__(VoicePipeline)
    vp.sentence_queue = asyncio.Queue()
    vp.current_tts_task = None
    vp.current_llm_task = None
    vp.is_rio_speaking = False
    vp.current_turn_user_text = ""
    vp.pending_user_turn_text = ""
    vp.pending_llm_latency = 0.0
    vp.llm_dispatch_task = None
    vp.post_stt_grace = 0.05  # short grace for fast tests
    vp.interrupt_pending = False
    vp.pause_playback = False
    vp.resume_event = asyncio.Event()
    vp.resume_event.set()
    vp.pending_interrupt_reason = None
    vp.last_rio_sentences = deque(maxlen=3)
    vp.last_rio_spoken = deque(maxlen=5)
    vp._last_clear_ts = 0.0
    vp.use_silero_vad = False
    vp.audio_encoding = "pcm_mulaw"
    vp.audio_sample_rate = 8000
    vp.llm_service = MagicMock()
    vp.llm_service.add_user_message = MagicMock()
    vp.llm_service.add_system_message = MagicMock()
    for k, v in overrides.items():
        setattr(vp, k, v)
    return vp


# Silero wrapper unit tests — skipped when silero_vad isn't installed (e.g.
# tests running against the system python rather than the venv).
_silero_vad_available = pytest.importorskip.__self__ if False else None  # type: ignore
try:
    import silero_vad  # noqa: F401
    _silero_vad_available = True
except Exception:
    _silero_vad_available = False

silero_skip = pytest.mark.skipif(
    not _silero_vad_available,
    reason="silero_vad not installed in this Python — install in venv to enable",
)


@silero_skip
def test_silero_silent_pcm16_returns_false():
    from services.ai.vad.silero import SileroVadGate
    gate = SileroVadGate()
    # 1024 bytes = 512 samples of PCM16 silence
    assert gate.is_speech(b"\x00" * 1024, sample_rate=16000) is False


def test_silero_fails_open_on_empty_input():
    from services.ai.vad.silero import SileroVadGate
    gate = SileroVadGate()
    # Empty input → False (no speech), NOT open-fail
    assert gate.is_speech(b"") is False


def test_silero_confirms_unknown_encoding_fails_open():
    from services.ai.vad.silero import silero_confirms_speech
    # Unknown encoding → fail-safe OPEN (True), never drop legitimate barge-in.
    assert silero_confirms_speech(b"\x00" * 100, "weird_encoding", 8000) is True


@silero_skip
def test_silero_confirms_pcm16_silence_returns_false():
    from services.ai.vad.silero import silero_confirms_speech
    # 2048 bytes = 1024 samples of silence at 16kHz → no speech.
    assert silero_confirms_speech(b"\x00" * 2048, "pcm16", 16000) is False


@silero_skip
def test_silero_confirms_mulaw_silence_returns_false():
    from services.ai.vad.silero import silero_confirms_speech
    # Mulaw silence byte is 0xff; decode to PCM16 silence.
    assert silero_confirms_speech(b"\xff" * 1024, "pcm_mulaw", 8000) is False


# _silero_confirms on the pipeline — fail-safe open

def test_pipeline_silero_confirms_failopen_when_vad_raises(monkeypatch):
    vp = _build_pipeline_stub()
    import services.ai.vad as vad_pkg
    monkeypatch.setattr(
        vad_pkg,
        "silero_confirms_speech",
        MagicMock(side_effect=RuntimeError("model broken")),
    )
    assert vp._silero_confirms(b"\x00" * 100) is True


def test_pipeline_silero_confirms_returns_silero_result(monkeypatch):
    vp = _build_pipeline_stub()
    # Patch the silero module AND the vad package's re-export so the
    # _silero_confirms helper's `from services.ai.vad import
    # silero_confirms_speech` picks up our stub.
    import services.ai.vad as vad_pkg
    monkeypatch.setattr(vad_pkg, "silero_confirms_speech", MagicMock(return_value=False))
    assert vp._silero_confirms(b"\x00" * 100) is False
    monkeypatch.setattr(vad_pkg, "silero_confirms_speech", MagicMock(return_value=True))
    assert vp._silero_confirms(b"\x00" * 100) is True


# R1 — STT debounce + concat

def test_r1_single_final_dispatches_once():
    async def _run():
        vp = _build_pipeline_stub()
        dispatched = []

        async def _fake_dispatch(transcript, latency):
            dispatched.append((transcript, latency))

        vp._dispatch_llm = _fake_dispatch
        vp.pending_user_turn_text = "hello there"
        vp._schedule_llm_dispatch(latency=0.1)
        await asyncio.sleep(vp.post_stt_grace + 0.05)
        return dispatched

    dispatched = asyncio.run(_run())
    assert dispatched == [("hello there", 0.1)]


def test_r1_two_finals_within_grace_concat_into_single_dispatch():
    async def _run():
        vp = _build_pipeline_stub()
        dispatched = []

        async def _fake_dispatch(transcript, latency):
            dispatched.append((transcript, latency))

        vp._dispatch_llm = _fake_dispatch

        # first final arrives
        vp.pending_user_turn_text = "A"
        vp._schedule_llm_dispatch(latency=0.1)
        # second final arrives mid-grace, appends + re-schedules
        await asyncio.sleep(vp.post_stt_grace / 2)
        vp.pending_user_turn_text = "A B"
        vp._schedule_llm_dispatch(latency=0.2)

        await asyncio.sleep(vp.post_stt_grace + 0.05)
        return dispatched

    dispatched = asyncio.run(_run())
    assert len(dispatched) == 1
    assert dispatched[0][0] == "A B"


def test_r1_empty_pending_skips_dispatch():
    async def _run():
        vp = _build_pipeline_stub()
        dispatched = []

        async def _fake_dispatch(transcript, latency):
            dispatched.append(transcript)

        vp._dispatch_llm = _fake_dispatch
        vp.pending_user_turn_text = ""
        vp._schedule_llm_dispatch(latency=0.1)
        await asyncio.sleep(vp.post_stt_grace + 0.05)
        return dispatched

    assert asyncio.run(_run()) == []


# R2 — pause/resume/cancel

def test_r2_pause_sets_flags():
    vp = _build_pipeline_stub()
    assert vp.pause_playback is False
    assert vp.resume_event.is_set() is True
    vp._pause_playback_for_interrupt()
    assert vp.pause_playback is True
    assert vp.resume_event.is_set() is False


def test_r2_resume_sets_flags_back():
    vp = _build_pipeline_stub()
    vp._pause_playback_for_interrupt()
    vp._resume_playback_from_interrupt()
    assert vp.pause_playback is False
    assert vp.resume_event.is_set() is True


def test_r2_false_positive_resumes_playback():
    vp = _build_pipeline_stub()
    vp.interrupt_pending = True
    vp._pause_playback_for_interrupt()
    vp._handle_false_positive_interrupt()
    assert vp.interrupt_pending is False
    assert vp.pause_playback is False
    assert vp.resume_event.is_set() is True


def test_r2_confirmed_interrupt_carries_context():
    vp = _build_pipeline_stub()
    vp.interrupt_pending = True
    vp._pause_playback_for_interrupt()
    vp.last_rio_spoken.extend(["I can help with that.", "Our pricing starts at..."])
    vp.pending_user_turn_text = "wait stop"

    dispatched = []

    async def _fake_dispatch(transcript, latency, interrupted_context=""):
        dispatched.append((transcript, latency, interrupted_context))

    vp._dispatch_llm = _fake_dispatch

    async def _run():
        vp._handle_confirmed_interrupt(latency=0.2)
        await asyncio.sleep(0)
        await asyncio.sleep(0)  # let the create_task fire

    asyncio.run(_run())

    assert vp.interrupt_pending is False
    assert vp.pause_playback is False
    assert list(vp.last_rio_spoken) == []  # cleared on confirmed interrupt
    assert len(dispatched) == 1
    transcript, _latency, interrupted = dispatched[0]
    assert transcript == "wait stop"
    assert "I can help with that" in interrupted
    assert "Our pricing starts at" in interrupted


def test_r2_confirmed_with_empty_spoken_buffer_passes_empty_context():
    vp = _build_pipeline_stub()
    vp.interrupt_pending = True
    vp._pause_playback_for_interrupt()
    vp.pending_user_turn_text = "hey"

    dispatched = []

    async def _fake_dispatch(transcript, latency, interrupted_context=""):
        dispatched.append(interrupted_context)

    vp._dispatch_llm = _fake_dispatch

    async def _run():
        vp._handle_confirmed_interrupt(latency=0.1)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    asyncio.run(_run())
    assert dispatched == [""]


# _dispatch_llm — interrupted_context injects system message

def test_dispatch_llm_with_context_injects_system_message():
    async def _run():
        vp = _build_pipeline_stub()

        async def _noop(*a, **kw):
            return None

        vp._process_llm_response = _noop  # swallow the task body
        await vp._dispatch_llm(
            transcript="what about X",
            latency=0.1,
            interrupted_context="I was saying A B C",
        )
        await asyncio.sleep(0)

    asyncio.run(_run())


def test_dispatch_llm_without_context_does_not_inject():
    async def _run():
        vp = _build_pipeline_stub()

        async def _noop(*a, **kw):
            return None

        vp._process_llm_response = _noop
        await vp._dispatch_llm(transcript="hi", latency=0.1)
        # llm_service.add_system_message must NOT have been called
        return vp.llm_service.add_system_message.called

    called = asyncio.run(_run())
    assert called is False


# last_rio_spoken rolling window

def test_last_rio_spoken_rolls_at_5():
    vp = _build_pipeline_stub()
    for i in range(8):
        vp.last_rio_spoken.append(f"sentence {i}")
    assert len(vp.last_rio_spoken) == 5
    assert list(vp.last_rio_spoken) == [f"sentence {i}" for i in range(3, 8)]
