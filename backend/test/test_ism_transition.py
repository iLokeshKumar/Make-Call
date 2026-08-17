"""Unit tests for ISM (Intelligent Sales Machine) stage transitions.

Tests exercise the pure transition logic — no DB, no network.
Covers: stage ordering, forward-only advancement, terminal stages,
outcome-to-stage mapping, channel preferences, and helper functions.
"""
import pytest

from agents.ism_orchestrator import (
    ISM_STAGE_ORDER,
    _TERMINAL_STAGES,
    _STAGE_CHANNEL_PREFERENCE,
    _CHANNEL_COOLDOWN_HOURS,
    _CHANNEL_MAX_ATTEMPTS,
    _lead_has_channel,
    _stage_index,
)
from services.call.outcome_service import (
    OUTCOME_CALLBACK_REQUESTED,
    OUTCOME_FOLLOW_UP,
    OUTCOME_INTERESTED,
    OUTCOME_NOT_INTERESTED,
    _OUTCOME_ISM_STAGE,
    advance_ism_stage,
    derive_lead_status_patch,
)


class TestStageOrdering:
    def test_stage_order_is_correct(self):
        assert ISM_STAGE_ORDER == [
            "new", "contacted", "engaged", "quote_sent",
            "negotiation", "closed_won", "closed_lost",
        ]

    def test_stage_index_returns_position(self):
        assert _stage_index("new") == 0
        assert _stage_index("contacted") == 1
        assert _stage_index("closed_won") == 5
        assert _stage_index("closed_lost") == 6

    def test_stage_index_unknown_returns_zero(self):
        assert _stage_index("nonexistent") == 0


# advance_ism_stage — forward-only transitions

class TestAdvanceIsmStage:
    def test_forward_transition_succeeds(self, bare_lead):
        bare_lead.ism_stage = "new"
        assert advance_ism_stage(bare_lead, "contacted") is True
        assert bare_lead.ism_stage == "contacted"

    def test_skip_stages_allowed(self, bare_lead):
        bare_lead.ism_stage = "new"
        assert advance_ism_stage(bare_lead, "engaged") is True
        assert bare_lead.ism_stage == "engaged"

    def test_backward_transition_rejected(self, bare_lead):
        bare_lead.ism_stage = "engaged"
        assert advance_ism_stage(bare_lead, "contacted") is False
        assert bare_lead.ism_stage == "engaged"

    def test_same_stage_rejected(self, bare_lead):
        bare_lead.ism_stage = "contacted"
        assert advance_ism_stage(bare_lead, "contacted") is False
        assert bare_lead.ism_stage == "contacted"

    def test_advance_to_closed_won(self, bare_lead):
        bare_lead.ism_stage = "negotiation"
        assert advance_ism_stage(bare_lead, "closed_won") is True
        assert bare_lead.ism_stage == "closed_won"

    def test_advance_to_closed_lost(self, bare_lead):
        bare_lead.ism_stage = "new"
        assert advance_ism_stage(bare_lead, "closed_lost") is True
        assert bare_lead.ism_stage == "closed_lost"

    def test_none_stage_treated_as_new(self, bare_lead):
        bare_lead.ism_stage = None
        assert advance_ism_stage(bare_lead, "contacted") is True
        assert bare_lead.ism_stage == "contacted"

    def test_cannot_go_back_from_closed_won(self, bare_lead):
        bare_lead.ism_stage = "closed_won"
        assert advance_ism_stage(bare_lead, "new") is False
        assert advance_ism_stage(bare_lead, "negotiation") is False

    def test_closed_lost_to_closed_won_rejected(self, bare_lead):
        """closed_lost (index 6) > closed_won (index 5) — no backward."""
        bare_lead.ism_stage = "closed_lost"
        assert advance_ism_stage(bare_lead, "closed_won") is False


# Terminal stages

class TestTerminalStages:
    def test_closed_won_is_terminal(self):
        assert "closed_won" in _TERMINAL_STAGES

    def test_closed_lost_is_terminal(self):
        assert "closed_lost" in _TERMINAL_STAGES

    def test_do_not_call_is_terminal(self):
        assert "do_not_call" in _TERMINAL_STAGES

    def test_active_stages_are_not_terminal(self):
        for stage in ("new", "contacted", "engaged", "quote_sent", "negotiation"):
            assert stage not in _TERMINAL_STAGES


# Outcome → ISM stage mapping

class TestOutcomeToStageMapping:
    def test_interested_maps_to_engaged(self):
        assert _OUTCOME_ISM_STAGE[OUTCOME_INTERESTED] == "engaged"

    def test_callback_maps_to_contacted(self):
        assert _OUTCOME_ISM_STAGE[OUTCOME_CALLBACK_REQUESTED] == "contacted"

    def test_follow_up_maps_to_contacted(self):
        assert _OUTCOME_ISM_STAGE[OUTCOME_FOLLOW_UP] == "contacted"

    def test_not_interested_maps_to_closed_lost(self):
        assert _OUTCOME_ISM_STAGE[OUTCOME_NOT_INTERESTED] == "closed_lost"

    def test_interested_outcome_advances_lead(self, bare_lead):
        bare_lead.ism_stage = "contacted"
        target = _OUTCOME_ISM_STAGE[OUTCOME_INTERESTED]
        result = advance_ism_stage(bare_lead, target)
        assert result is True
        assert bare_lead.ism_stage == "engaged"


# derive_lead_status_patch

class TestDeriveLeadStatusPatch:
    def test_interested_returns_qualified(self):
        patch = derive_lead_status_patch(OUTCOME_INTERESTED)
        assert patch["status"] == "contacted"
        assert patch["qualification_status"] == "qualified"

    def test_not_interested_returns_closed_lost(self):
        patch = derive_lead_status_patch(OUTCOME_NOT_INTERESTED)
        assert patch["status"] == "closed_lost"
        assert patch["qualification_status"] == "not_interested"
        assert patch["next_action"] == "none"


# Channel preferences and guards

class TestChannelPreferences:
    def test_new_stage_prefers_call_first(self):
        assert _STAGE_CHANNEL_PREFERENCE["new"][0] == "call"

    def test_contacted_stage_prefers_whatsapp(self):
        assert _STAGE_CHANNEL_PREFERENCE["contacted"][0] == "whatsapp"

    def test_engaged_stage_prefers_email(self):
        assert _STAGE_CHANNEL_PREFERENCE["engaged"][0] == "email"

    def test_negotiation_stage_prefers_call(self):
        assert _STAGE_CHANNEL_PREFERENCE["negotiation"][0] == "call"

    def test_all_active_stages_have_preferences(self):
        for stage in ("new", "contacted", "engaged", "quote_sent", "negotiation"):
            assert stage in _STAGE_CHANNEL_PREFERENCE
            assert len(_STAGE_CHANNEL_PREFERENCE[stage]) == 3


class TestChannelGuards:
    def test_cooldown_hours_defined(self):
        assert _CHANNEL_COOLDOWN_HOURS["call"] == 24
        assert _CHANNEL_COOLDOWN_HOURS["whatsapp"] == 6
        assert _CHANNEL_COOLDOWN_HOURS["email"] == 12

    def test_max_attempts_defined(self):
        assert _CHANNEL_MAX_ATTEMPTS["call"] == 3
        assert _CHANNEL_MAX_ATTEMPTS["whatsapp"] == 5
        assert _CHANNEL_MAX_ATTEMPTS["email"] == 7


class TestLeadHasChannel:
    def test_call_needs_phone(self, bare_lead):
        assert _lead_has_channel(bare_lead, "call") is True
        bare_lead.normalized_phone = ""
        assert _lead_has_channel(bare_lead, "call") is False

    def test_whatsapp_needs_phone(self, bare_lead):
        assert _lead_has_channel(bare_lead, "whatsapp") is True
        bare_lead.normalized_phone = ""
        assert _lead_has_channel(bare_lead, "whatsapp") is False

    def test_email_needs_email(self, bare_lead):
        assert _lead_has_channel(bare_lead, "email") is False
        bare_lead.email = "test@example.com"
        assert _lead_has_channel(bare_lead, "email") is True

    def test_unknown_channel_returns_false(self, bare_lead):
        assert _lead_has_channel(bare_lead, "pigeon") is False
