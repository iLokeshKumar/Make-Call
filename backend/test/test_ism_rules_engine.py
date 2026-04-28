"""Tests for Week 3.3 — ISM Rules Engine.

Invariants:
  1. No rules → returns None (stage-default behavior preserved)
  2. Priority ordering: lower number wins; id breaks ties
  3. Inactive rules are skipped
  4. Every when_json operator behaves correctly for match AND non-match cases
  5. Missing data (no requirement row, null fields) fails closed (rule doesn't fire)
  6. Unknown operators in when_json fail closed (safer than firing spuriously)
  7. Action parsing is pure string manipulation — no side effects
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.models import IsmRule, Lead, LeadRequirement, utc_now
from agents.ism_rules_engine import evaluate_rules, parse_action


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


def _seed_lead(session: Session, **overrides) -> Lead:
    defaults = {
        "company_id": 1,
        "name": "Test Lead",
        "normalized_phone": "+919876543210",
        "email": "lead@example.com",
        "ism_stage": "engaged",
    }
    defaults.update(overrides)
    lead = Lead(**defaults)
    session.add(lead); session.commit(); session.refresh(lead)
    return lead


def _seed_rule(session: Session, **kwargs) -> IsmRule:
    defaults = {
        "company_id": 1,
        "name": "test-rule",
        "priority": 10,
        "when_json": {},
        "then_action": "skip",
        "is_active": True,
    }
    defaults.update(kwargs)
    rule = IsmRule(**defaults)
    session.add(rule); session.commit(); session.refresh(rule)
    return rule


# No rules → None

class TestNoRules:
    def test_empty_ruleset_returns_none(self, session):
        lead = _seed_lead(session)
        assert evaluate_rules(session, 1, lead) is None


# Priority ordering

class TestPriorityOrdering:
    def test_lower_priority_wins(self, session):
        lead = _seed_lead(session)
        # Both rules match (empty when_json); lower priority fires first
        high = _seed_rule(session, name="high_prio", priority=1, then_action="advance_to:negotiation")
        _seed_rule(session, name="low_prio", priority=100, then_action="handoff_to_human")

        result = evaluate_rules(session, 1, lead)
        assert result is not None
        assert result.id == high.id

    def test_id_breaks_priority_tie(self, session):
        """Rules at same priority → lowest id wins (stable ordering)."""
        lead = _seed_lead(session)
        first = _seed_rule(session, name="first", priority=10, then_action="skip")
        _seed_rule(session, name="second", priority=10, then_action="skip")

        result = evaluate_rules(session, 1, lead)
        assert result.id == first.id

    def test_inactive_rules_skipped(self, session):
        lead = _seed_lead(session)
        _seed_rule(session, name="disabled", priority=1, is_active=False,
                   then_action="advance_to:closed_won")
        active = _seed_rule(session, name="active", priority=10,
                            then_action="handoff_to_human")

        result = evaluate_rules(session, 1, lead)
        assert result.id == active.id


# Simple when_json operators

class TestStageOperators:
    def test_stage_exact_match(self, session):
        lead = _seed_lead(session, ism_stage="engaged")
        _seed_rule(session, when_json={"stage": "engaged"}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_stage_no_match(self, session):
        lead = _seed_lead(session, ism_stage="new")
        _seed_rule(session, when_json={"stage": "engaged"}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None

    def test_stages_list_any_match(self, session):
        lead = _seed_lead(session, ism_stage="quote_sent")
        _seed_rule(session, when_json={"stages": ["engaged", "quote_sent", "negotiation"]},
                   then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_stages_list_no_match(self, session):
        lead = _seed_lead(session, ism_stage="new")
        _seed_rule(session, when_json={"stages": ["engaged", "quote_sent"]},
                   then_action="skip")
        assert evaluate_rules(session, 1, lead) is None


class TestContactFieldOperators:
    def test_has_email_true_matches(self, session):
        lead = _seed_lead(session, email="x@y.z")
        _seed_rule(session, when_json={"has_email": True}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_has_email_false_matches_when_missing(self, session):
        lead = _seed_lead(session, email="")
        _seed_rule(session, when_json={"has_email": False}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_has_phone_true(self, session):
        lead = _seed_lead(session, normalized_phone="+1")
        _seed_rule(session, when_json={"has_phone": True}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_has_phone_false_when_present_no_match(self, session):
        lead = _seed_lead(session, normalized_phone="+1")
        _seed_rule(session, when_json={"has_phone": False}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None


class TestLeadScoreOperators:
    def test_lead_score_min_matches_above(self, session):
        lead = _seed_lead(session)
        lead.lead_score = Decimal("75.0")
        session.add(lead); session.commit()
        _seed_rule(session, when_json={"lead_score_min": 50}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_lead_score_min_no_match_below(self, session):
        lead = _seed_lead(session)
        lead.lead_score = Decimal("30.0")
        session.add(lead); session.commit()
        _seed_rule(session, when_json={"lead_score_min": 50}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None

    def test_lead_score_missing_fails_closed(self, session):
        """Null lead_score → score condition can't be satisfied → rule doesn't fire."""
        lead = _seed_lead(session)
        # default lead_score is None
        _seed_rule(session, when_json={"lead_score_min": 50}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None


class TestDaysSinceContactOperators:
    def test_never_contacted_satisfies_min(self, session):
        """A lead with last_outreach_at=None has been 'out of touch' forever
        → any days_since_contact_min matches."""
        lead = _seed_lead(session)
        _seed_rule(session, when_json={"days_since_contact_min": 7}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_never_contacted_fails_max(self, session):
        """Never contacted → definitely longer than any days_since_contact_max."""
        lead = _seed_lead(session)
        _seed_rule(session, when_json={"days_since_contact_max": 7}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None

    def test_recent_contact_satisfies_max(self, session):
        lead = _seed_lead(session)
        lead.last_outreach_at = utc_now() - timedelta(days=3)
        session.add(lead); session.commit()
        _seed_rule(session, when_json={"days_since_contact_max": 7}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_old_contact_satisfies_min(self, session):
        lead = _seed_lead(session)
        lead.last_outreach_at = utc_now() - timedelta(days=10)
        session.add(lead); session.commit()
        _seed_rule(session, when_json={"days_since_contact_min": 7}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None


# Requirement-dependent operators

class TestRequirementOperators:
    def _seed_requirement(self, session, lead, **fields):
        req = LeadRequirement(company_id=1, lead_id=lead.id, **fields)
        session.add(req); session.commit(); session.refresh(req)
        return req

    def test_budget_usd_min_with_free_text(self, session):
        lead = _seed_lead(session)
        self._seed_requirement(session, lead, budget_range="$50k")
        _seed_rule(session, when_json={"budget_usd_min": 25000}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_budget_usd_min_under_threshold(self, session):
        lead = _seed_lead(session)
        self._seed_requirement(session, lead, budget_range="$5k")
        _seed_rule(session, when_json={"budget_usd_min": 25000}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None

    def test_budget_usd_min_inr_conversion(self, session):
        lead = _seed_lead(session)
        # 50 lakh INR ≈ $62.5k USD → should match 25k threshold
        self._seed_requirement(session, lead, budget_range="50 lakh")
        _seed_rule(session, when_json={"budget_usd_min": 25000}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_budget_structured_data_wins_over_text(self, session):
        lead = _seed_lead(session)
        self._seed_requirement(session, lead,
                               budget_range="$100k",  # text says high
                               structured_data={"budget_max_usd": 5000})  # explicit says low
        _seed_rule(session, when_json={"budget_usd_min": 25000}, then_action="skip")
        # explicit structured value wins → $5k < $25k → no match
        assert evaluate_rules(session, 1, lead) is None

    def test_budget_no_requirement_fails_closed(self, session):
        """No LeadRequirement row → budget condition can't be satisfied."""
        lead = _seed_lead(session)
        _seed_rule(session, when_json={"budget_usd_min": 25000}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None

    def test_urgency_urgent_matches_keyword(self, session):
        lead = _seed_lead(session)
        self._seed_requirement(session, lead, timeline="ASAP please")
        _seed_rule(session, when_json={"urgency": "urgent"}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_urgency_routine_when_no_urgent_keyword(self, session):
        lead = _seed_lead(session)
        self._seed_requirement(session, lead, timeline="next quarter")
        _seed_rule(session, when_json={"urgency": "routine"}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_urgency_structured_data_override(self, session):
        lead = _seed_lead(session)
        self._seed_requirement(session, lead,
                               timeline="next quarter",  # text is routine
                               structured_data={"urgency": "urgent"})  # explicit is urgent
        _seed_rule(session, when_json={"urgency": "urgent"}, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None


# Multiple operators AND-combined

class TestMultipleOperatorsAndCombined:
    def test_all_must_match(self, session):
        lead = _seed_lead(session, ism_stage="engaged", email="x@y.z")
        _seed_rule(session, when_json={
            "stage": "engaged",
            "has_email": True,
        }, then_action="skip")
        assert evaluate_rules(session, 1, lead) is not None

    def test_one_fail_breaks_the_rule(self, session):
        lead = _seed_lead(session, ism_stage="engaged", email="")
        _seed_rule(session, when_json={
            "stage": "engaged",
            "has_email": True,   # this fails
        }, then_action="skip")
        assert evaluate_rules(session, 1, lead) is None


# Defensive: unknown operators

class TestUnknownOperatorFailsClosed:
    def test_unknown_operator_means_rule_does_not_fire(self, session):
        lead = _seed_lead(session)
        _seed_rule(session, when_json={"not_a_real_operator": "whatever"},
                   then_action="skip")
        # Safer to fail closed than fire on unrecognized operator
        assert evaluate_rules(session, 1, lead) is None


# Empty when_json = catch-all

class TestEmptyWhenJsonMatches:
    def test_empty_conditions_match_everything(self, session):
        lead = _seed_lead(session)
        _seed_rule(session, when_json={}, then_action="handoff_to_human")
        result = evaluate_rules(session, 1, lead)
        assert result is not None
        assert result.then_action == "handoff_to_human"


# parse_action

class TestParseAction:
    @pytest.mark.parametrize("action,expected", [
        ("advance_to:negotiation", ("advance_to", "negotiation")),
        ("dispatch:send_email",    ("dispatch", "send_email")),
        ("handoff_to_human",       ("handoff_to_human", None)),
        ("skip",                   ("skip", None)),
        ("",                       ("skip", None)),           # empty → safe default
        ("advance_to:",            ("advance_to", None)),     # colon but empty arg
        ("  skip  ",               ("skip", None)),           # trimming
    ])
    def test_parse_variations(self, action, expected):
        assert parse_action(action) == expected
