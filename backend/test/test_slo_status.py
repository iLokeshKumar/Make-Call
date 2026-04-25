"""Tests for Week 8.2 — SLO computation, alerting, soft-launch."""
from __future__ import annotations

import asyncio
import os
import sys
import types
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


# Stubs for any provider SDKs that might pull in via worker imports
for _missing in ("groq", "anthropic", "google", "google.generativeai", "cerebras", "openai", "pyotp"):
    if _missing not in sys.modules:
        sys.modules[_missing] = types.ModuleType(_missing)


@pytest.fixture
def engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def _reset_state():
    from services.observability.request_metrics import _reset_for_tests as reset_req
    reset_req()
    yield
    reset_req()


# Percentile helper

def test_percentile_returns_none_for_empty():
    from services.observability.slo import _percentile
    assert _percentile([], 95) is None


def test_percentile_one_value():
    from services.observability.slo import _percentile
    assert _percentile([42.0], 95) == 42.0


def test_percentile_p95():
    from services.observability.slo import _percentile
    vals = [float(i) for i in range(1, 101)]
    p95 = _percentile(vals, 95)
    # statistics.quantiles(method="inclusive") puts p95 ≈ 95
    assert 90 <= p95 <= 100


# Voice p95 SLO

def test_voice_slo_insufficient_data(session):
    from services.observability.slo import _slo_voice_p95
    out = _slo_voice_p95(session, company_id=1)
    assert out["status"] == "insufficient_data"
    assert out["actual"] is None


def test_voice_slo_breach_when_p95_above_target(session):
    from models.models import LatencyLog
    # Seed 20 rows all at 1500ms
    for _ in range(20):
        session.add(LatencyLog(
            company_id=1,
            stt_ms=400, llm_ms=700, tts_ms=400, total_ms=1500,
            engine="mistral",
        ))
    session.commit()
    from services.observability.slo import _slo_voice_p95
    out = _slo_voice_p95(session, company_id=1)
    assert out["status"] == "breach"
    assert out["actual"] >= 800
    assert out["samples"] == 20


def test_voice_slo_ok_when_p95_below_target(session):
    from models.models import LatencyLog
    for _ in range(20):
        session.add(LatencyLog(
            company_id=1,
            stt_ms=100, llm_ms=300, tts_ms=200, total_ms=600,
            engine="mistral",
        ))
    session.commit()
    from services.observability.slo import _slo_voice_p95
    out = _slo_voice_p95(session, company_id=1)
    assert out["status"] == "ok"
    assert out["actual"] <= 800


# Login → dashboard SLO

def test_login_dashboard_slo_uses_fmp_event_only(session):
    from models.models import UiLatencyLog
    # Seed 20 fmp at 800ms + 20 ttfb at 5000ms (must be ignored)
    for _ in range(20):
        session.add(UiLatencyLog(company_id=1, route="/", event="fmp", duration_ms=800))
    for _ in range(20):
        session.add(UiLatencyLog(company_id=1, route="/", event="ttfb", duration_ms=5000))
    session.commit()
    from services.observability.slo import _slo_login_dashboard_p95
    out = _slo_login_dashboard_p95(session, company_id=1)
    assert out["status"] == "ok"
    assert out["samples"] == 20


# Dead-letter SLO

def test_dead_letter_rate_excludes_old_jobs(session):
    from models.models import BackgroundJob
    cutoff_old = datetime.now(timezone.utc) - timedelta(days=10)
    # 12 old dead_letter rows (should be ignored due to 7d window)
    for _ in range(12):
        session.add(BackgroundJob(
            company_id=1, job_type="post_call_workflow", status="dead_letter",
            payload={}, created_at=cutoff_old,
        ))
    session.commit()
    from services.observability.slo import _slo_dead_letter_rate
    out = _slo_dead_letter_rate(session, company_id=1)
    assert out["status"] == "insufficient_data"
    assert out["samples"] == 0


def test_dead_letter_rate_breach(session):
    from models.models import BackgroundJob
    # 100 jobs, 5 dead_letter → 5% breach (>0.5% target)
    for i in range(95):
        session.add(BackgroundJob(
            company_id=1, job_type="post_call_workflow", status="done", payload={},
        ))
    for i in range(5):
        session.add(BackgroundJob(
            company_id=1, job_type="post_call_workflow", status="dead_letter", payload={},
        ))
    session.commit()
    from services.observability.slo import _slo_dead_letter_rate
    out = _slo_dead_letter_rate(session, company_id=1)
    assert out["status"] == "breach"
    assert out["samples"] == 100
    assert abs(out["actual"] - 0.05) < 0.001


# API availability SLO

def test_api_availability_excludes_options():
    from services.observability.request_metrics import record_response, get_availability_snapshot
    record_response("OPTIONS", 200)  # excluded
    record_response("OPTIONS", 200)
    record_response("OPTIONS", 500)
    snap = get_availability_snapshot()
    assert snap["total"] == 0


def test_api_availability_counts_5xx():
    from services.observability.request_metrics import record_response, get_availability_snapshot
    for _ in range(95):
        record_response("GET", 200)
    for _ in range(5):
        record_response("GET", 500)
    snap = get_availability_snapshot()
    assert snap["total"] == 100
    assert snap["five_xx"] == 5
    assert abs(snap["availability"] - 0.95) < 0.001


def test_api_availability_slo_classification():
    from services.observability.request_metrics import record_response
    from services.observability.slo import _slo_api_availability
    # 99.0% — below 99.5% target → breach
    for _ in range(99):
        record_response("GET", 200)
    record_response("GET", 500)
    out = _slo_api_availability()
    assert out["status"] == "breach"


# Slack alert dispatch

def test_slack_no_op_when_env_unset(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    from services.alerts.notify import _post_slack
    ok = asyncio.run(_post_slack("subject", "body"))
    assert ok is False


def test_slack_posts_when_env_set(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    from services.alerts import notify as notify_mod

    captured = {}

    class _StubResponse:
        status_code = 200

    class _StubClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return _StubResponse()

    monkeypatch.setattr(notify_mod, "httpx", types.SimpleNamespace(AsyncClient=_StubClient))
    ok = asyncio.run(notify_mod._post_slack("subj", "body"))
    assert ok is True
    assert captured["url"].startswith("https://hooks.slack.com")
    assert "subj" in captured["json"]["text"]


# Worker dedupe + soft-launch

def test_slo_alerts_disabled_until_enabled_at(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    monkeypatch.setenv("SLO_ALERTS_ENABLED_AT", future)
    from services.automation_worker_service import _slo_alerts_enabled
    assert _slo_alerts_enabled() is False


def test_slo_alerts_enabled_when_past():
    from services.automation_worker_service import _slo_alerts_enabled
    # No env set → default enabled
    if "SLO_ALERTS_ENABLED_AT" in os.environ:
        del os.environ["SLO_ALERTS_ENABLED_AT"]
    assert _slo_alerts_enabled() is True


def test_slo_eval_throttle_skips_within_15min(session, monkeypatch):
    from services.automation_worker_service import (
        _maybe_evaluate_slos_and_alert,
        _reset_slo_throttles_for_tests,
    )
    _reset_slo_throttles_for_tests()
    monkeypatch.setenv("SLO_ALERTS_ENABLED_AT", "")  # default enabled
    first = _maybe_evaluate_slos_and_alert(session, company_id=1)
    second = _maybe_evaluate_slos_and_alert(session, company_id=1)
    assert "skipped" not in first or first.get("skipped") in (None, "soft_launch_window")
    assert second.get("skipped") == "throttled_15min"


# UI latency model smoke (importing the route directly drags qrcode/pyotp/etc.
# via auth.py — for the pure-pydantic validation we skip the route import).
