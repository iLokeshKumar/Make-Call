"""Unit tests for outcome classification and retry policy.

Tests exercise normalize_call_outcome, classify_outcome_from_transcript,
get_retry_policy, and _suggest_action_from_outcome — all pure functions,
no DB required.
"""
from decimal import Decimal

from services.call.outcome_service import (
    OUTCOME_ANSWERED,
    OUTCOME_BUSY,
    OUTCOME_CALLBACK_REQUESTED,
    OUTCOME_FAILED,
    OUTCOME_FOLLOW_UP,
    OUTCOME_INTERESTED,
    OUTCOME_NO_ANSWER,
    OUTCOME_NOT_INTERESTED,
    OUTCOME_VOICEMAIL,
    classify_outcome_from_transcript,
    get_retry_policy,
    normalize_call_outcome,
)


# normalize_call_outcome — direct status passthrough

class TestNormalizeDirectStatus:
    def test_already_canonical_passes_through(self):
        for outcome in (OUTCOME_INTERESTED, OUTCOME_NOT_INTERESTED, OUTCOME_BUSY,
                        OUTCOME_NO_ANSWER, OUTCOME_FAILED, OUTCOME_VOICEMAIL):
            assert normalize_call_outcome(outcome) == outcome

    def test_busy_status(self):
        assert normalize_call_outcome("busy") == OUTCOME_BUSY

    def test_no_answer_variants(self):
        for status in ("no-answer", "no_answer", "ringing", "canceled", "cancelled"):
            assert normalize_call_outcome(status) == OUTCOME_NO_ANSWER, f"Failed for {status}"

    def test_voicemail_variants(self):
        for status in ("voicemail", "machine", "answering_machine"):
            assert normalize_call_outcome(status) == OUTCOME_VOICEMAIL, f"Failed for {status}"

    def test_failed_variants(self):
        for status in ("failed", "error"):
            assert normalize_call_outcome(status) == OUTCOME_FAILED, f"Failed for {status}"

    def test_none_status_returns_failed(self):
        assert normalize_call_outcome(None) == OUTCOME_FAILED

    def test_unknown_status_returns_failed(self):
        assert normalize_call_outcome("something_random") == OUTCOME_FAILED


# normalize_call_outcome — transcript signal detection

class TestNormalizeWithTranscript:
    def test_positive_signal_returns_interested(self):
        assert normalize_call_outcome("completed", "Yes I'm interested in pricing") == OUTCOME_INTERESTED

    def test_negative_signal_returns_not_interested(self):
        assert normalize_call_outcome("completed", "No thanks, not interested") == OUTCOME_NOT_INTERESTED

    def test_callback_signal_returns_callback(self):
        assert normalize_call_outcome("completed", "Can you call me back tomorrow?") == OUTCOME_CALLBACK_REQUESTED

    def test_neutral_transcript_returns_follow_up(self):
        assert normalize_call_outcome("completed", "I see, let me think about it") == OUTCOME_FOLLOW_UP

    def test_negative_beats_positive_when_both_present(self):
        # "not interested" appears before any positive signal
        result = normalize_call_outcome("completed", "not interested in a demo")
        assert result == OUTCOME_NOT_INTERESTED

    def test_callback_beats_positive(self):
        # "call me back" checked before positive signals
        result = normalize_call_outcome("completed", "call me back, sounds good")
        assert result == OUTCOME_CALLBACK_REQUESTED

    def test_answered_status_also_triggers_detection(self):
        assert normalize_call_outcome("answered", "send me a proposal") == OUTCOME_INTERESTED

    def test_in_progress_status_also_triggers_detection(self):
        assert normalize_call_outcome("in_progress", "not now") == OUTCOME_NOT_INTERESTED


# classify_outcome_from_transcript

class TestClassifyFromTranscript:
    def test_empty_transcript_returns_failed(self):
        result = classify_outcome_from_transcript(None, "")
        assert result["normalized_outcome"] == OUTCOME_FAILED
        assert result["confidence"] == Decimal("0.25")
        assert result["signals"] == []

    def test_none_transcript_returns_failed(self):
        result = classify_outcome_from_transcript(None, None)
        assert result["normalized_outcome"] == OUTCOME_FAILED

    def test_positive_transcript_heuristic(self):
        result = classify_outcome_from_transcript(
            None, "Yes please send me the proposal and pricing"
        )
        assert result["normalized_outcome"] == OUTCOME_INTERESTED
        assert result["confidence"] == Decimal("0.70")
        assert any("positive" in s or "signal_" in s for s in result["signals"])
        assert result["suggested_next_action"] == "send_quote"

    def test_negative_transcript_heuristic(self):
        result = classify_outcome_from_transcript(
            None, "No I'm not interested, please stop calling"
        )
        assert result["normalized_outcome"] == OUTCOME_NOT_INTERESTED
        assert result["suggested_next_action"] == "close_lost"

    def test_callback_transcript_heuristic(self):
        # Use "call me back" without "later" (which is a negative signal)
        result = classify_outcome_from_transcript(
            None, "Sure, call me back in the evening please"
        )
        assert result["normalized_outcome"] == OUTCOME_CALLBACK_REQUESTED
        assert result["suggested_next_action"] == "follow_up_call"

    def test_summary_truncated_to_240(self):
        long_text = "word " * 200  # 1000 chars
        result = classify_outcome_from_transcript(None, long_text)
        assert len(result["summary"]) <= 240

    def test_llm_fallback_on_failure(self):
        """When LLM raises, heuristic result is used."""

        class BrokenLLM:
            def invoke(self, prompt):
                raise RuntimeError("LLM down")

        result = classify_outcome_from_transcript(
            BrokenLLM(), "I'm interested in a demo"
        )
        assert result["normalized_outcome"] == OUTCOME_INTERESTED

    def test_llm_invalid_json_falls_back(self):
        class BadJsonLLM:
            def invoke(self, prompt):
                return "this is not json"

        result = classify_outcome_from_transcript(
            BadJsonLLM(), "send me the quote"
        )
        assert result["normalized_outcome"] == OUTCOME_INTERESTED


# get_retry_policy

class TestRetryPolicy:
    def test_no_answer_retries_up_to_6(self):
        policy = get_retry_policy(OUTCOME_NO_ANSWER, 0)
        assert policy["should_retry"] is True
        assert policy["max_attempts"] == 6
        assert policy["retry_after_hours"] == 1

    def test_no_answer_escalating_backoff(self):
        hours = []
        for attempt in range(6):
            p = get_retry_policy(OUTCOME_NO_ANSWER, attempt)
            if p["retry_after_hours"]:
                hours.append(p["retry_after_hours"])
        assert hours == [1, 2, 4, 8, 16, 24]

    def test_no_answer_exhausted_at_6(self):
        policy = get_retry_policy(OUTCOME_NO_ANSWER, 6)
        assert policy["should_retry"] is False
        assert policy["max_attempts_reached"] is True

    def test_busy_retries_up_to_4(self):
        policy = get_retry_policy(OUTCOME_BUSY, 0)
        assert policy["should_retry"] is True
        assert policy["max_attempts"] == 4

    def test_interested_no_retry(self):
        policy = get_retry_policy(OUTCOME_INTERESTED, 0)
        assert policy["should_retry"] is False

    def test_not_interested_no_retry(self):
        policy = get_retry_policy(OUTCOME_NOT_INTERESTED, 0)
        assert policy["should_retry"] is False

    def test_voicemail_retries_twice(self):
        p0 = get_retry_policy(OUTCOME_VOICEMAIL, 0)
        assert p0["should_retry"] is True
        assert p0["retry_after_hours"] == 24

        p1 = get_retry_policy(OUTCOME_VOICEMAIL, 1)
        assert p1["should_retry"] is True
        assert p1["retry_after_hours"] == 72

        p2 = get_retry_policy(OUTCOME_VOICEMAIL, 2)
        assert p2["should_retry"] is False

    def test_unknown_outcome_no_retry(self):
        policy = get_retry_policy("some_random_outcome", 0)
        assert policy["should_retry"] is False
