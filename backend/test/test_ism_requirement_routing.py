"""Tests for Week 2.1 — LeadRequirement-driven channel selection.

Lock down two pure-function parsers (`_budget_is_high_ticket`,
`_timeline_is_urgent`) and the integration into `_pick_channel`.

The parsers are deliberately conservative: anything unparseable returns False.
False negatives just fall through to stage-based default (the pre-2.1 behavior),
so they're always safe. False positives would force the wrong channel and
that's what we're guarding against.
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

from types import SimpleNamespace

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import Lead, LeadRequirement, utc_now
from agents.ism_orchestrator import (
    _budget_is_high_ticket,
    _pick_channel,
    _requirement_preferred_channels,
    _timeline_is_urgent,
)


# Fixtures

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


def _make_requirement(**fields) -> LeadRequirement:
    """Build a LeadRequirement instance without inserting (for pure parser tests)."""
    defaults = {"company_id": 1, "lead_id": 1}
    defaults.update(fields)
    return LeadRequirement(**defaults)


def _insert_lead_and_requirement(session: Session, **req_fields) -> tuple[Lead, LeadRequirement]:
    """Insert a Lead + one LeadRequirement row and return both."""
    lead = Lead(
        company_id=1, name="Test Lead",
        normalized_phone="+919876543210", email="lead@example.com",
    )
    session.add(lead); session.commit(); session.refresh(lead)

    req = _make_requirement(lead_id=lead.id, **req_fields)
    session.add(req); session.commit(); session.refresh(req)
    return lead, req


# _budget_is_high_ticket

class TestBudgetParser:
    @pytest.mark.parametrize("budget,expected", [
        # USD
        ("$50k",           True),
        ("50k",            True),
        ("15k USD",        True),
        ("$15000",         True),
        ("$9k",            False),
        ("5k",             False),
        ("$9,999",         False),
        ("10-50k",         True),      # max(10k, 50k) = 50k → high
        ("up to $100k",    True),
        # INR (rough ÷80)
        ("5 lakh",         False),      # 500k INR ≈ $6.25k → not high
        ("10 lakh",        True),       # 1M INR ≈ $12.5k → high
        ("50 lakh",        True),
        ("1 crore",        True),
        ("₹800000",        True),       # 800k INR ≈ $10k → exactly threshold
        # Edge cases — fall to False
        ("",               False),
        ("TBD",            False),
        ("flexible",       False),
        ("enterprise",     False),
    ])
    def test_parsing_various_formats(self, budget, expected):
        req = _make_requirement(budget_range=budget)
        assert _budget_is_high_ticket(req) is expected, f"budget={budget!r}"

    def test_structured_data_wins_over_text(self):
        """Explicit structured_data.budget_max_usd overrides ambiguous text."""
        req = _make_requirement(
            budget_range="TBD",
            structured_data={"budget_max_usd": 50000},
        )
        assert _budget_is_high_ticket(req) is True

    def test_structured_data_rejects_low_budget(self):
        req = _make_requirement(
            budget_range="$1M",  # text says high
            structured_data={"budget_max_usd": 5000},  # structured says low — wins
        )
        assert _budget_is_high_ticket(req) is False

    def test_structured_data_invalid_falls_through(self):
        """Non-numeric structured_data.budget_max_usd → fall back to text."""
        req = _make_requirement(
            budget_range="$50k",
            structured_data={"budget_max_usd": "not-a-number"},
        )
        assert _budget_is_high_ticket(req) is True  # text wins


# _timeline_is_urgent

class TestTimelineParser:
    @pytest.mark.parametrize("timeline,expected", [
        ("urgent",                 True),
        ("ASAP",                   True),
        ("immediately",            True),
        ("this week",              True),
        ("next 7 days",            True),
        ("tomorrow",               True),
        ("rush order",             True),
        # Not urgent
        ("next quarter",           False),
        ("Q2 2026",                False),
        ("3 months",               False),
        ("flexible",               False),
        ("",                       False),
        ("sometime",               False),
    ])
    def test_keyword_detection(self, timeline, expected):
        req = _make_requirement(timeline=timeline)
        assert _timeline_is_urgent(req) is expected, f"timeline={timeline!r}"

    def test_structured_data_urgency_wins(self):
        req = _make_requirement(
            timeline="flexible",
            structured_data={"urgency": "urgent"},
        )
        assert _timeline_is_urgent(req) is True

    def test_structured_data_casing_insensitive(self):
        req = _make_requirement(structured_data={"urgency": "URGENT"})
        assert _timeline_is_urgent(req) is True


# _requirement_preferred_channels (reads from DB)

class TestRequirementPreferredChannels:
    def test_no_requirement_returns_none(self, session):
        # Lead exists, no requirement row → None (fall through to stage default)
        lead = Lead(company_id=1, name="x", normalized_phone="+911", email="x@y.z")
        session.add(lead); session.commit(); session.refresh(lead)
        assert _requirement_preferred_channels(session, 1, lead.id) is None

    def test_high_budget_prefers_call(self, session):
        lead, _ = _insert_lead_and_requirement(session, budget_range="$50k", timeline="")
        assert _requirement_preferred_channels(session, 1, lead.id) == ["call", "whatsapp", "email"]

    def test_urgent_not_high_budget_prefers_whatsapp(self, session):
        lead, _ = _insert_lead_and_requirement(session, budget_range="$5k", timeline="ASAP")
        assert _requirement_preferred_channels(session, 1, lead.id) == ["whatsapp", "call", "email"]

    def test_high_budget_wins_over_urgent(self, session):
        """When both signals fire, high-ticket takes priority over urgent."""
        lead, _ = _insert_lead_and_requirement(session, budget_range="$50k", timeline="urgent")
        assert _requirement_preferred_channels(session, 1, lead.id) == ["call", "whatsapp", "email"]

    def test_neither_signal_returns_none(self, session):
        """Requirement exists but neither field triggers — fall through to stage default."""
        lead, _ = _insert_lead_and_requirement(session, budget_range="$3k", timeline="next quarter")
        assert _requirement_preferred_channels(session, 1, lead.id) is None

    def test_latest_requirement_wins(self, session):
        """Multiple requirement rows — use the most recent by created_at."""
        lead = Lead(company_id=1, name="x", normalized_phone="+911", email="x@y.z")
        session.add(lead); session.commit(); session.refresh(lead)

        req_old = _make_requirement(lead_id=lead.id, budget_range="$3k")
        session.add(req_old); session.commit(); session.refresh(req_old)

        req_new = _make_requirement(lead_id=lead.id, budget_range="$50k")
        session.add(req_new); session.commit(); session.refresh(req_new)

        # Newer row has higher budget → high-ticket preference
        assert _requirement_preferred_channels(session, 1, lead.id) == ["call", "whatsapp", "email"]


# _pick_channel integration

class TestPickChannelIntegration:
    """_pick_channel should use requirement override when available, respect
    all existing guards (opt-out / cooldown / exhaustion / missing contact)."""

    def test_no_requirement_uses_stage_default(self, session):
        """Without requirement, behavior is identical to pre-2.1 — stage decides."""
        lead = Lead(company_id=1, name="x", normalized_phone="+911", email="x@y.z")
        session.add(lead); session.commit(); session.refresh(lead)
        # "new" stage default is [call, whatsapp, email] → first available wins
        assert _pick_channel(session, 1, lead, stage="new") == "call"

    def test_high_budget_overrides_contacted_stage(self, session):
        """Stage 'contacted' prefers whatsapp; high budget forces call."""
        lead, _ = _insert_lead_and_requirement(session, budget_range="$100k", timeline="")
        assert _pick_channel(session, 1, lead, stage="contacted") == "call"

    def test_high_budget_but_no_phone_falls_to_email(self, session):
        """Requirement says 'call', but lead has no phone → respect contact fields."""
        lead = Lead(company_id=1, name="x", normalized_phone="", email="x@y.z")
        session.add(lead); session.commit(); session.refresh(lead)
        req = _make_requirement(lead_id=lead.id, budget_range="$50k")
        session.add(req); session.commit()

        # Preference order is [call, whatsapp, email]; call/whatsapp need phone → email
        assert _pick_channel(session, 1, lead, stage="new") == "email"
