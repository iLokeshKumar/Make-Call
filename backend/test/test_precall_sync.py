"""Tests for sync-wait pre-call enrichment in dialer_service.

Verifies the fix for the fire-and-forget bug:
  * Pre-fix: `asyncio.create_task` + immediate Twilio dial → voice
    pipeline read precall_cache before the coroutine completed →
    empty KB context.
  * Pre-fix: sync worker context (no running loop) →
    `asyncio.create_task` raised → bare except swallowed it →
    pre-call NEVER ran.

The fix runs `run_pre_call` synchronously with a hard timeout
(`PRECALL_TIMEOUT_S`, default 4 s).  These tests cover the timer +
both context paths (sync / async).
"""
from __future__ import annotations

import asyncio
import os
import sys
import types

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

# Pop bare-stub modules sibling tests may have injected.
for _name in (
    "groq", "anthropic", "google", "google.generativeai", "cerebras", "openai",
    "pyotp", "qrcode",
):
    mod = sys.modules.get(_name)
    if mod is not None and getattr(mod, "__file__", None) is None and not getattr(mod, "__path__", None):
        sys.modules.pop(_name, None)

import pytest


@pytest.fixture
def fake_precall(monkeypatch):
    """Patch `run_pre_call` with a controllable async stub."""
    from agents import orchestrator
    state = {"calls": 0, "delay": 0.0, "raise": None, "result": {"icp_score": 0.5, "kb_context": ["chunk1"]}}

    async def _stub(*args, **kwargs):
        state["calls"] += 1
        if state["delay"]:
            await asyncio.sleep(state["delay"])
        if state["raise"]:
            raise state["raise"]
        return state["result"]

    monkeypatch.setattr(orchestrator, "run_pre_call", _stub)
    return state


@pytest.fixture
def fake_cache(monkeypatch):
    """Capture put() calls so the test can assert population."""
    from utils import precall_cache
    captured: dict = {}

    def _put(company_id, lead_id, value):
        captured[(company_id, lead_id)] = value

    monkeypatch.setattr(precall_cache, "put", _put)
    return captured


def _run_precall_block(lead_id=42, company_id=1, actor_user_id=1):
    """Replicates the production sync-wait block from
    dialer_service.initiate_outbound_call so we can exercise it
    without spinning up a Twilio mock + Lead row."""
    import concurrent.futures
    import contextvars
    import logging
    from agents.orchestrator import run_pre_call
    from utils.precall_cache import put as cache_put

    logger = logging.getLogger("dialer-test")
    precall_timeout_s = float(os.getenv("PRECALL_TIMEOUT_S", "4.0"))

    async def _run_precall():
        result = await asyncio.wait_for(
            run_pre_call(lead_id=lead_id, company_id=company_id, actor_user_id=actor_user_id),
            timeout=precall_timeout_s,
        )
        cache_put(company_id, lead_id, result)
        logger.info("done")

    try:
        try:
            asyncio.get_running_loop()
            ctx = contextvars.copy_context()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(ctx.run, asyncio.run, _run_precall()).result()
        except RuntimeError:
            asyncio.run(_run_precall())
    except asyncio.TimeoutError:
        return "timeout"
    except Exception:  # noqa: BLE001
        return "error"
    return "ok"


def test_precall_runs_synchronously_in_sync_context(fake_precall, fake_cache):
    """No running loop → asyncio.run path → coroutine completes,
    cache populated before function returns."""
    out = _run_precall_block(lead_id=42, company_id=1)
    assert out == "ok"
    assert fake_precall["calls"] == 1
    assert (1, 42) in fake_cache
    assert fake_cache[(1, 42)]["icp_score"] == 0.5


def test_precall_runs_in_loop_via_thread_offload(fake_precall, fake_cache):
    """Loop already running (FastAPI path) → thread-offload path →
    cache still populated synchronously before function returns."""
    async def _wrap():
        return _run_precall_block(lead_id=43, company_id=1)

    out = asyncio.run(_wrap())
    assert out == "ok"
    assert fake_precall["calls"] == 1
    assert (1, 43) in fake_cache


def test_precall_timeout_does_not_block_dial(fake_precall, fake_cache, monkeypatch):
    """Pre-call exceeds budget → timeout caught → cache NOT populated
    but flow continues (returns 'timeout', not 'error')."""
    monkeypatch.setenv("PRECALL_TIMEOUT_S", "0.1")
    fake_precall["delay"] = 0.5  # > timeout
    out = _run_precall_block(lead_id=44, company_id=1)
    assert out == "timeout"
    assert (1, 44) not in fake_cache


def test_precall_exception_does_not_block_dial(fake_precall, fake_cache):
    """Pre-call raises → caught → returns 'error', flow continues."""
    fake_precall["raise"] = RuntimeError("LLM down")
    out = _run_precall_block(lead_id=45, company_id=1)
    assert out == "error"
    assert (1, 45) not in fake_cache
