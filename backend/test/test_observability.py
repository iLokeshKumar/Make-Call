"""Tests for Week 8.3 — observability polish.

Covers:
* trace_id inheritance in create_agent_task (explicit > ContextVar > None)
* request_id_var → AgentTask.trace_id propagation
* Mistral 15-min sliding 429 counter
"""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

# Note: rate_limit_metrics lives in services.observability — independent of
# any LLM provider package — so no SDK stubs are needed here.

import pytest  # noqa: E402
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import AgentTask, EmailOutbox


# Stubs to avoid heavy SDK loads
_stub_call = types.ModuleType("call")
_stub_call_outbound = types.ModuleType("call.outbound_call_service")
_stub_call_outbound.create_call_task = lambda **kw: types.SimpleNamespace(id=0)
_stub_call.outbound_call_service = _stub_call_outbound
sys.modules.setdefault("call", _stub_call)
sys.modules.setdefault("call.outbound_call_service", _stub_call_outbound)


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
def _reset_request_id():
    from utils.logger import request_id_var
    token = request_id_var.set("-")
    yield
    try:
        request_id_var.reset(token)
    except Exception:
        pass


# trace_id inheritance — create_agent_task

def test_trace_id_explicit_wins(session):
    from utils.logger import request_id_var
    from services.agent.agent_task_service import create_agent_task

    request_id_var.set("ctx-rid")
    task = create_agent_task(
        session=session,
        company_id=1,
        task_type="enrich_lead",
        assigned_agent="researcher",
        input_json={},
        idempotency_key="test-explicit",
        trace_id="explicit-rid",
    )
    assert task.trace_id == "explicit-rid"


def test_trace_id_inherits_request_id_var(session):
    from utils.logger import request_id_var
    from services.agent.agent_task_service import create_agent_task

    request_id_var.set("ctx-from-http")
    task = create_agent_task(
        session=session,
        company_id=1,
        task_type="enrich_lead",
        assigned_agent="researcher",
        input_json={},
        idempotency_key="test-ctx",
    )
    assert task.trace_id == "ctx-from-http"


def test_trace_id_none_when_no_context_and_not_passed(session):
    # request_id_var defaults to "-" via fixture; resolver treats "-" as missing
    from services.agent.agent_task_service import create_agent_task

    task = create_agent_task(
        session=session,
        company_id=1,
        task_type="enrich_lead",
        assigned_agent="researcher",
        input_json={},
        idempotency_key="test-none",
    )
    assert task.trace_id is None


def test_trace_id_truncated_to_64_chars(session):
    from services.agent.agent_task_service import create_agent_task

    long_id = "x" * 200
    task = create_agent_task(
        session=session,
        company_id=1,
        task_type="enrich_lead",
        assigned_agent="researcher",
        input_json={},
        idempotency_key="test-long",
        trace_id=long_id,
    )
    assert task.trace_id == "x" * 64


# Resolver helper

def test_resolve_trace_id_helper_priority():
    from utils.logger import request_id_var
    from services.agent.agent_task_service import _resolve_trace_id

    # explicit > ctxvar
    request_id_var.set("ctx-x")
    assert _resolve_trace_id("explicit") == "explicit"
    # ctxvar when no explicit
    assert _resolve_trace_id(None) == "ctx-x"
    # neither → None
    request_id_var.set("-")
    assert _resolve_trace_id(None) is None


# EmailOutbox request_id capture

def test_email_outbox_captures_request_id(session, monkeypatch):
    from utils.logger import request_id_var
    from services.communication.email_outbox_service import enqueue_email

    request_id_var.set("rid-from-handler")
    item = enqueue_email(
        session=session,
        company_id=1,
        actor_user_id=1,
        to_email="x@example.com",
        subject="t",
        body="b",
        html_body=None,
        dedupe_key="x-1",
    )
    fetched = session.get(EmailOutbox, item.id)
    assert fetched.request_id == "rid-from-handler"


def test_email_outbox_no_request_id_when_unset(session):
    from services.communication.email_outbox_service import enqueue_email

    # Default fixture sets request_id_var to "-" — resolver treats as missing
    item = enqueue_email(
        session=session,
        company_id=1,
        actor_user_id=1,
        to_email="x@example.com",
        subject="t",
        body="b",
        html_body=None,
        dedupe_key="x-2",
    )
    fetched = session.get(EmailOutbox, item.id)
    assert fetched.request_id is None


# 15-min sliding 429 counter (provider-agnostic)

def test_rate_limit_counter_records_and_returns():
    from services.observability.rate_limit_metrics import (
        record_rate_limit_hit,
        get_rate_limit_hits_last_15min,
        _reset_for_tests,
    )
    _reset_for_tests()
    assert get_rate_limit_hits_last_15min() == 0
    record_rate_limit_hit()
    record_rate_limit_hit()
    record_rate_limit_hit()
    assert get_rate_limit_hits_last_15min() == 3


def test_rate_limit_counter_evicts_old_entries():
    import time as _time
    from services.observability import rate_limit_metrics as rl

    rl._reset_for_tests()
    rl._rate_limit_hits.append(_time.monotonic() - rl._RATE_LIMIT_WINDOW_SECONDS - 100)
    rl._rate_limit_hits.append(_time.monotonic())
    assert rl.get_rate_limit_hits_last_15min() == 1
