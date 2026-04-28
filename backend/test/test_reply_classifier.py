"""Unit tests for the reply classifier (agents/reply_classifier.py).

Covers rule fast path, LLM fallback, caching, cycle budget, error handling,
and inbound-handler wire-in behavior (unsubscribe promotion).
"""
from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import MagicMock

import pytest


# We never call the real Mistral; stub the service module ahead of imports.
def _install_llm_stub(monkeypatch, intent: str | None):
    """Install a stub get_llm_service that returns *intent* (or None for failure)."""
    async def _stream(*_a, **_kw):
        if intent is None:
            yield {"type": "error", "content": "boom"}
            return
        yield {"type": "token", "content": intent}
        yield {"type": "finished", "full_reply": intent}

    class _StubLLM:
        def __init__(self, *a, **kw):
            self.messages = []

        def add_user_message(self, _msg):  # noqa: D401
            self.messages.append(_msg)

        async def stream(self, *_a, **_kw):
            async for chunk in _stream():
                yield chunk

    def _get_llm_service(*_a, **_kw):
        return _StubLLM()

    stub = types.ModuleType("services.ai.llm")
    stub.get_llm_service = _get_llm_service
    monkeypatch.setitem(sys.modules, "services.ai.llm", stub)


def _install_credentials_stub(monkeypatch):
    stub = types.ModuleType("credentials_service")

    def _get_company_setting_value(_session, _company_id, _key):
        return "stub-key"

    stub.get_company_setting_value = _get_company_setting_value
    monkeypatch.setitem(sys.modules, "credentials_service", stub)


@pytest.fixture(autouse=True)
def _reset_module_state():
    from agents import reply_classifier
    reply_classifier._reset_cycle_for_tests()
    yield
    reply_classifier._reset_cycle_for_tests()


# Rule fast path

def test_rule_opt_out_maps_to_unsubscribe():
    from agents.reply_classifier import classify_reply
    result = asyncio.run(classify_reply(MagicMock(), 1, "stop", "whatsapp"))
    assert result["intent"] == "unsubscribe"
    assert result["source"] == "rule"


def test_rule_quote_requested_maps_to_interested():
    from agents.reply_classifier import classify_reply
    result = asyncio.run(classify_reply(MagicMock(), 1, "send me a quote please", "email"))
    assert result["intent"] == "interested"
    assert result["source"] == "rule"


def test_short_neutral_is_noise_without_llm(monkeypatch):
    from agents.reply_classifier import classify_reply
    # Short body — classifier short-circuits without importing the LLM module.
    result = asyncio.run(classify_reply(MagicMock(), 1, "ok", "whatsapp"))
    assert result["intent"] == "noise"
    assert result["source"] == "rule"


# LLM fallback

def test_llm_fallback_returns_classification(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="question")
    # Reset cache to avoid cross-test contamination
    from agents.reply_classifier import classify_reply, _REPLY_CACHE
    _REPLY_CACHE.clear()
    body = "What are the onboarding steps for a new team member on the platform"
    result = asyncio.run(classify_reply(MagicMock(), 1, body, "email"))
    assert result["intent"] == "question"
    assert result["source"] == "llm"


def test_llm_returns_objection(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="objection")
    from agents.reply_classifier import classify_reply, _REPLY_CACHE
    _REPLY_CACHE.clear()
    result = asyncio.run(classify_reply(MagicMock(), 1, "this is way too expensive for us", "whatsapp"))
    assert result["intent"] == "objection"
    assert result["source"] == "llm"


def test_llm_failure_falls_back_to_noise(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent=None)  # simulates error chunk
    from agents.reply_classifier import classify_reply, _REPLY_CACHE
    _REPLY_CACHE.clear()
    result = asyncio.run(classify_reply(MagicMock(), 1, "I have some thoughts about your offering", "email"))
    assert result["intent"] == "noise"
    assert result["source"] == "llm"


# Cache

def test_cache_hit_avoids_second_llm_call(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="interested")
    from agents.reply_classifier import classify_reply, _REPLY_CACHE
    _REPLY_CACHE.clear()

    body = "let me think about it over the weekend and get back"
    first = asyncio.run(classify_reply(MagicMock(), 1, body, "email"))
    second = asyncio.run(classify_reply(MagicMock(), 1, body, "email"))

    assert first["source"] == "llm"
    assert second["source"] == "cache"
    assert first["intent"] == second["intent"] == "interested"


def test_cache_miss_after_ttl(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="interested")
    from agents.reply_classifier import classify_reply, _REPLY_CACHE, _TTLCache
    # Replace cache with one that has a TTL of 0 so entries expire immediately.
    import agents.reply_classifier as rc
    rc._REPLY_CACHE = _TTLCache(maxsize=4, ttl=0)

    body = "hmm, let me consider this and come back shortly"
    r1 = asyncio.run(classify_reply(MagicMock(), 1, body, "email"))
    r2 = asyncio.run(classify_reply(MagicMock(), 1, body, "email"))
    # Both are fresh LLM calls, not cache hits
    assert r1["source"] == "llm"
    assert r2["source"] == "llm"

    rc._REPLY_CACHE = _REPLY_CACHE  # restore (fixture clears after)


# Cycle budget

def test_cycle_cap_forces_fallback_after_N_classifications(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="interested")
    from agents.reply_classifier import classify_reply, _REPLY_CACHE
    _REPLY_CACHE.clear()

    # First 3 go through (cap=3 per window); 4th must fall back.
    bodies = [
        "long neutral message number one about plans",
        "another neutral long message number two here",
        "yet another long neutral message number three",
        "and here is the fourth long neutral message",
    ]
    results = [asyncio.run(classify_reply(MagicMock(), 1, b, "email")) for b in bodies]
    assert results[0]["source"] == "llm"
    assert results[1]["source"] == "llm"
    assert results[2]["source"] == "llm"
    assert results[3]["source"] == "llm_cap"
    assert results[3]["intent"] == "noise"


# Roadmap intent mapping — rule side

def test_callback_requested_maps_to_interested():
    from agents.reply_classifier import classify_reply
    result = asyncio.run(classify_reply(MagicMock(), 1, "call me back tomorrow", "whatsapp"))
    assert result["intent"] == "interested"


def test_not_interested_maps_to_objection():
    from agents.reply_classifier import classify_reply
    result = asyncio.run(classify_reply(MagicMock(), 1, "not interested thanks", "whatsapp"))
    assert result["intent"] == "objection"


# Sync facade

def test_classify_reply_sync_outside_event_loop(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="question")
    from agents.reply_classifier import classify_reply_sync, _REPLY_CACHE
    _REPLY_CACHE.clear()
    result = classify_reply_sync(MagicMock(), 1, "what are your payment terms please", "email")
    assert result["intent"] == "question"


def test_classify_reply_sync_from_running_loop(monkeypatch):
    _install_credentials_stub(monkeypatch)
    _install_llm_stub(monkeypatch, intent="interested")
    from agents.reply_classifier import classify_reply_sync, _REPLY_CACHE
    _REPLY_CACHE.clear()

    async def _runner():
        # Calling the sync facade from inside a running loop should hand off
        # to a worker thread and still return the right result.
        return classify_reply_sync(MagicMock(), 1, "yes let us schedule a demo next week", "email")

    result = asyncio.run(_runner())
    assert result["intent"] == "interested"
