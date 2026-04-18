"""
Shared pytest fixtures for Rio CRM backend tests.

These fixtures provide lightweight mock objects that mirror SQLModel models
without requiring a database connection. Tests that need a real DB session
should create their own fixtures or use a test database.

The sys.path and stub-module setup below lets pure business-logic functions
be imported without pulling in the full DB / network dependency chain.
"""
from __future__ import annotations

import sys
import os
import types
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

import pytest

# Path setup: backend/ and backend/services/ must be importable

_backend_dir = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, _backend_dir)
sys.path.insert(0, os.path.join(_backend_dir, "services"))


# ---------------------------------------------------------------------------
# Stub modules that depend on DB / network at import time.
#
# These stubs satisfy `from X import Y` at the module level without actually
# loading the real modules (which would pull in sqlalchemy, httpx, etc.).
# Only the leaf-level modules that cause import errors need stubs — the
# functions under test are pure logic with no DB dependency.
# ---------------------------------------------------------------------------
def _stub_module(name: str, attrs: dict | None = None) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in (attrs or {}).items():
        setattr(mod, k, v)
    sys.modules.setdefault(name, mod)
    return mod


def _noop(*a, **kw):
    return None


# outcome_service imports outbound_call_service at module level
_stub_module("outbound_call_service", {"get_call_task_or_404": _noop})

# demand_generation_service → from call.outbound_call_service import create_call_task
_stub_module("call", {})
_stub_module("call.outbound_call_service", {"create_call_task": _noop, "get_call_task_or_404": _noop})

# communication_service → from communication.email_outbox_service import enqueue_email
_stub_module("communication", {})
_stub_module("communication.email_outbox_service", {"enqueue_email": _noop, "process_outbox_batch": _noop})
_stub_module("communication.communication_service", {
    "get_company_setting_value": _noop,
    "send_email_to_lead": _noop,
    "send_whatsapp_to_lead": _noop,
    "send_quote_to_lead": _noop,
})
_stub_module("communication.inbound_whatsapp_service", {"classify_reply_intent": _noop})


# Mock Lead dataclass — mirrors models.models.Lead without SQLModel

@dataclass
class MockLead:
    """Lightweight stand-in for models.models.Lead — no DB required."""

    id: int = 1
    company_id: int = 1
    name: str = "Test Lead"
    normalized_phone: str = "+919876543210"
    email: Optional[str] = None
    job_title: Optional[str] = None
    industry: Optional[str] = None
    website: Optional[str] = None
    source: str = "manual"
    enrichment_status: str = "not_enriched"
    status: str = "new"
    qualification_status: str = "unqualified"
    ism_stage: Optional[str] = "new"
    lead_score: Optional[Decimal] = None
    lead_score_reasons_json: Optional[dict] = None


# Fixtures

@pytest.fixture
def bare_lead() -> MockLead:
    """Lead with no enrichment — minimum viable fields only."""
    return MockLead()


@pytest.fixture
def enriched_lead() -> MockLead:
    """Fully enriched decision-maker from a high-intent source."""
    return MockLead(
        email="ceo@techcorp.com",
        website="https://techcorp.com",
        industry="tech",
        job_title="CEO",
        source="apollo",
        enrichment_status="fully_enriched",
    )


@pytest.fixture
def partial_lead() -> MockLead:
    """Partially enriched lead — email + non-target industry."""
    return MockLead(
        email="contact@randomshop.com",
        industry="hospitality",
        source="manual",
        enrichment_status="not_enriched",
    )
