"""Tests for resolve_call_context — verifies no cross-tenant fallback.

PR bot finding P1.2: prior code picked the first User in the DB when neither
user_id nor lead.owner_user_id resolved a target.  In a multi-tenant DB that
silently re-attributes the call to a foreign tenant.  These tests pin the
fixed behaviour: missing context → return None (caller rejects the call).
"""
from __future__ import annotations

import os
import sys
import types

os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

# When running under the venv python, all provider SDKs (groq, anthropic,
# google.*, etc.) are real and importable.  Other test modules in this
# suite stub them with bare ModuleType objects to support running on the
# system python.  Those stubs leak into sys.modules and break submodule
# resolution here (e.g. `from anthropic import AsyncAnthropic` fails when
# the cached anthropic is a bare ModuleType).
#
# Strategy: pop any stubbed entries that are bare ModuleType (no __file__)
# so a fresh, real import happens.  Idempotent — leaves real modules alone.
_STUB_NAMES = (
    "groq", "anthropic", "google", "google.generativeai", "cerebras", "openai",
    "pyotp", "qrcode", "google.auth", "google.auth.transport",
    "google.auth.transport.requests", "google.oauth2", "google_auth_oauthlib",
)
for _name in _STUB_NAMES:
    mod = sys.modules.get(_name)
    if mod is not None and getattr(mod, "__file__", None) is None and not getattr(mod, "__path__", None):
        sys.modules.pop(_name, None)

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine


@pytest.fixture
def engine():
    # Re-pop any stale stub modules left behind by sibling test modules
    # (test_voice_pipeline_interrupts.py stubs anthropic/google/etc.) so
    # main.py can import the real SDKs.  Idempotent.
    for _name in (
        "groq", "anthropic", "google", "google.generativeai", "cerebras", "openai",
        "pyotp", "qrcode", "google.auth", "google.auth.transport",
        "google.auth.transport.requests", "google.oauth2", "google_auth_oauthlib",
    ):
        mod = sys.modules.get(_name)
        if mod is not None and getattr(mod, "__file__", None) is None and not getattr(mod, "__path__", None):
            sys.modules.pop(_name, None)

    # Import models BEFORE create_all so SQLModel.metadata knows about every table.
    import models.models  # noqa: F401
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


def _seed_user(session, *, user_id: int, company_id: int, email: str | None = None):
    from models.models import User
    u = User(
        id=user_id,
        company_id=company_id,
        email=email or f"u{user_id}@c{company_id}.test",
        password_hash="x",
    )
    session.add(u)
    session.commit()
    return u


def _seed_lead(session, *, lead_id: int, company_id: int, owner_user_id: int | None = None):
    from models.models import Lead
    lead = Lead(
        id=lead_id,
        company_id=company_id,
        name=f"Lead {lead_id}",
        normalized_phone=f"+1555000{lead_id:04d}",
        owner_user_id=owner_user_id,
    )
    session.add(lead)
    session.commit()
    return lead


def test_no_user_no_lead_returns_none_none(session):
    from main import resolve_call_context
    user, lead = resolve_call_context(session, None, None)
    assert user is None
    assert lead is None


def test_missing_user_does_not_pick_arbitrary_first_user(session):
    """The legacy fallback `select(User).first()` is gone.  Even with users
    in the DB, missing user_id + missing lead → None."""
    from main import resolve_call_context
    _seed_user(session, user_id=1, company_id=1)
    _seed_user(session, user_id=2, company_id=2)

    user, lead = resolve_call_context(session, None, None)
    assert user is None
    assert lead is None


def test_zero_user_id_treated_as_missing(session):
    from main import resolve_call_context
    _seed_user(session, user_id=1, company_id=1)
    user, _ = resolve_call_context(session, "0", None)
    assert user is None


def test_explicit_user_id_resolves(session):
    from main import resolve_call_context
    _seed_user(session, user_id=42, company_id=7)
    user, _ = resolve_call_context(session, "42", None)
    assert user is not None
    assert user.id == 42
    assert user.company_id == 7


def test_lead_owner_resolves_user_when_no_user_id(session):
    from main import resolve_call_context
    _seed_user(session, user_id=10, company_id=5)
    _seed_lead(session, lead_id=100, company_id=5, owner_user_id=10)
    user, lead = resolve_call_context(session, None, "100")
    assert user is not None and user.id == 10
    assert lead is not None and lead.id == 100


def test_lead_dropped_on_tenant_mismatch(session):
    """If user_id and lead_id resolve to different tenants, lead binding
    must be dropped (cross-tenant data leak prevention)."""
    from main import resolve_call_context
    _seed_user(session, user_id=10, company_id=5)
    _seed_lead(session, lead_id=200, company_id=99)  # different tenant
    user, lead = resolve_call_context(session, "10", "200")
    assert user is not None and user.company_id == 5
    assert lead is None  # dropped — tenant mismatch
