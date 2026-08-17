"""Tests for Week 4.1a — ism_rules CRUD route validation.

Direct validation of the DSL guards without spinning up a FastAPI test client.
The route handlers delegate all DSL validation to `_validate_when_json` and
`_validate_then_action` — those are the critical contracts.

Full HTTP-level tests require auth + DB setup which is the RLS test's territory
(Week 5 adds that coverage via a Postgres CI service container).
"""
from __future__ import annotations

import os
os.environ.setdefault("RLS_WARN_ON_MISSING", "0")

import pytest
from fastapi import HTTPException

from services.agent.ism_rules_validation import validate_then_action as _validate_then_action
from services.agent.ism_rules_validation import validate_when_json as _validate_when_json


# when_json validation

class TestWhenJsonValidation:
    def test_empty_dict_is_valid(self):
        _validate_when_json({})  # no exception

    def test_valid_operators_pass(self):
        _validate_when_json({"stage": "engaged"})
        _validate_when_json({"stages": ["engaged", "quote_sent"]})
        _validate_when_json({"has_email": True, "lead_score_min": 50})
        _validate_when_json({"budget_usd_min": 10000, "urgency": "urgent"})

    def test_unknown_operator_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_when_json({"not_a_real_operator": 42})
        assert exc.value.status_code == 400
        assert "not_a_real_operator" in exc.value.detail

    def test_non_dict_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_when_json("not a dict")
        assert exc.value.status_code == 400

    def test_unknown_in_mixed_valid_still_rejected(self):
        """Having SOME valid operators doesn't redeem an invalid one."""
        with pytest.raises(HTTPException):
            _validate_when_json({"stage": "engaged", "unknown_op": 1})


# then_action validation

class TestThenActionValidation:
    @pytest.mark.parametrize("action", [
        "advance_to:engaged",
        "advance_to:closed_lost",
        "dispatch:call",
        "dispatch:whatsapp",
        "dispatch:email",
        "dispatch:send_quote",
        "handoff_to_human",
        "skip",
    ])
    def test_valid_actions_pass(self, action):
        _validate_then_action(action)  # no exception

    def test_unknown_verb_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_then_action("nuke:everything")
        assert exc.value.status_code == 400
        assert "nuke" in exc.value.detail

    def test_advance_to_with_invalid_stage_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_then_action("advance_to:nonsense_stage")
        assert exc.value.status_code == 400
        assert "nonsense_stage" in exc.value.detail

    def test_advance_to_with_missing_stage_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_then_action("advance_to:")
        assert exc.value.status_code == 400

    def test_dispatch_with_invalid_channel_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_then_action("dispatch:telepathy")
        assert exc.value.status_code == 400

    def test_empty_action_raises_400(self):
        with pytest.raises(HTTPException) as exc:
            _validate_then_action("")
        assert exc.value.status_code == 400

    def test_whitespace_preserved_around_verb(self):
        """partition keeps surrounding whitespace — validator must strip before comparison."""
        _validate_then_action("  skip  ")  # should not raise
        _validate_then_action("advance_to:  engaged  ")  # arg has whitespace but stripped
