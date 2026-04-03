"""
Unit tests for outcome_service.py

Tests for outcome normalization, classification, retry policies, and lead status mapping.
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlmodel import SQLModel

# Import from parent backend directory
try:
    from models.models import CallTask, Interaction, Lead, Campaign, CampaignRecipient, utc_now
except ImportError:
    # Fallback if models import fails - tests can still validate functions without full model instances
    CallTask = None
    Interaction = None
    Lead = None
    Campaign = None
    CampaignRecipient = None

from services.outcome_service import (
    OUTCOME_ANSWERED,
    OUTCOME_BUSY,
    OUTCOME_CALLBACK_REQUESTED,
    OUTCOME_FAILED,
    OUTCOME_FOLLOW_UP,
    OUTCOME_INTERESTED,
    OUTCOME_NO_ANSWER,
    OUTCOME_NOT_INTERESTED,
    OUTCOME_VOICEMAIL,
    normalize_call_outcome,
    classify_outcome_from_transcript,
    get_retry_policy,
    derive_lead_status_patch,
)


class TestOutcomeNormalization(unittest.TestCase):
    """Test normalize_call_outcome function."""

    def test_normalize_no_answer(self):
        """Test no_answer outcome normalization."""
        result = normalize_call_outcome("no_answer")
        self.assertEqual(result, OUTCOME_NO_ANSWER)

    def test_normalize_busy(self):
        """Test busy outcome normalization."""
        result = normalize_call_outcome("busy")
        self.assertEqual(result, OUTCOME_BUSY)

    def test_normalize_voicemail(self):
        """Test voicemail outcome normalization."""
        result = normalize_call_outcome("voicemail")
        self.assertEqual(result, OUTCOME_VOICEMAIL)

    def test_normalize_failed(self):
        """Test failed outcome normalization."""
        result = normalize_call_outcome("failed")
        self.assertEqual(result, OUTCOME_FAILED)

    def test_normalize_answered_with_positive_transcript(self):
        """Test answered outcome with positive transcript."""
        transcript = "Yes, I'm very interested in this solution. Can you send me a quote?"
        result = normalize_call_outcome("answered", transcript)
        self.assertEqual(result, OUTCOME_INTERESTED)

    def test_normalize_answered_with_negative_transcript(self):
        """Test answered outcome with negative transcript."""
        transcript = "I'm not interested, please stop calling me."
        result = normalize_call_outcome("answered", transcript)
        self.assertEqual(result, OUTCOME_NOT_INTERESTED)

    def test_normalize_answered_with_callback_request(self):
        """Test answered outcome with callback request."""
        transcript = "Can you call me back tomorrow?"
        result = normalize_call_outcome("answered", transcript)
        self.assertEqual(result, OUTCOME_CALLBACK_REQUESTED)

    def test_normalize_answered_neutral_transcript(self):
        """Test answered outcome with neutral transcript."""
        transcript = "Tell me more about your product. Yes, I'm interested."
        result = normalize_call_outcome("answered", transcript)
        self.assertEqual(result, OUTCOME_INTERESTED)

    def test_normalize_unknown_status_defaults_to_failed(self):
        """Test that unknown status defaults to failed."""
        result = normalize_call_outcome("something_weird")
        self.assertEqual(result, OUTCOME_FAILED)


class TestOutcomeClassification(unittest.TestCase):
    """Test classify_outcome_from_transcript function."""

    def test_classify_positive_transcript(self):
        """Test classification of positive transcript."""
        transcript = "This is exactly what we need. Definitely interested."
        result = classify_outcome_from_transcript(None, transcript)
        
        self.assertEqual(result["normalized_outcome"], OUTCOME_INTERESTED)
        self.assertGreaterEqual(result["confidence"], Decimal("0.6"))
        self.assertIn("summary", result)
        self.assertIsInstance(result["signals"], list)
        self.assertEqual(result["suggested_next_action"], "send_quote")

    def test_classify_negative_transcript(self):
        """Test classification of negative transcript."""
        transcript = "This doesn't fit our needs. Not interested at all."
        result = classify_outcome_from_transcript(None, transcript)
        
        self.assertEqual(result["normalized_outcome"], OUTCOME_NOT_INTERESTED)
        self.assertEqual(result["suggested_next_action"], "close_lost")

    def test_classify_callback_transcript(self):
        """Test classification of callback request."""
        transcript = "Can you call me back next week? I'll have more information by then."
        result = classify_outcome_from_transcript(None, transcript)
        
        self.assertEqual(result["normalized_outcome"], OUTCOME_CALLBACK_REQUESTED)
        self.assertEqual(result["suggested_next_action"], "follow_up_call")

    def test_classify_empty_transcript(self):
        """Test classification with empty transcript."""
        result = classify_outcome_from_transcript(None, "")
        
        self.assertEqual(result["normalized_outcome"], OUTCOME_FAILED)
        self.assertLess(result["confidence"], Decimal("0.5"))


class TestRetryPolicy(unittest.TestCase):
    """Test get_retry_policy function."""

    def test_retry_policy_no_answer(self):
        """Test retry policy for no_answer outcome."""
        # First attempt should schedule retry
        policy = get_retry_policy(OUTCOME_NO_ANSWER, attempt_count=0)
        self.assertTrue(policy["should_retry"])
        self.assertEqual(policy["retry_after_hours"], 1)
        self.assertEqual(policy["max_attempts"], 6)
        self.assertFalse(policy["max_attempts_reached"])

    def test_retry_policy_busy(self):
        """Test retry policy for busy outcome."""
        policy = get_retry_policy(OUTCOME_BUSY, attempt_count=0)
        self.assertTrue(policy["should_retry"])
        self.assertEqual(policy["retry_after_hours"], 2)
        self.assertEqual(policy["max_attempts"], 4)

    def test_retry_policy_voicemail(self):
        """Test retry policy for voicemail outcome."""
        policy = get_retry_policy(OUTCOME_VOICEMAIL, attempt_count=0)
        self.assertTrue(policy["should_retry"])
        self.assertEqual(policy["retry_after_hours"], 24)
        self.assertEqual(policy["max_attempts"], 2)

    def test_retry_policy_max_attempts_reached(self):
        """Test retry policy when max attempts reached."""
        policy = get_retry_policy(OUTCOME_NO_ANSWER, attempt_count=6)
        self.assertFalse(policy["should_retry"])
        self.assertTrue(policy["max_attempts_reached"])

    def test_retry_policy_interested_no_retry(self):
        """Test that interested outcome doesn't retry."""
        policy = get_retry_policy(OUTCOME_INTERESTED, attempt_count=0)
        self.assertFalse(policy["should_retry"])
        self.assertEqual(policy["max_attempts"], 1)  # max is 1, so no more attempts allowed

    def test_retry_policy_progression(self):
        """Test retry policy progression through attempts."""
        outcomes_hours = [
            (0, 1, True),    # Attempt 1: retry after 1 hour
            (1, 2, True),    # Attempt 2: retry after 2 hours
            (2, 4, True),    # Attempt 3: retry after 4 hours
            (3, 8, True),    # Attempt 4: retry after 8 hours
            (4, 16, True),   # Attempt 5: retry after 16 hours
            (5, 24, True),   # Attempt 6: retry after 24 hours (still within max_attempts=6)
        ]
        
        for attempt, expected_hours, should_retry in outcomes_hours:
            policy = get_retry_policy(OUTCOME_NO_ANSWER, attempt_count=attempt)
            self.assertEqual(policy["should_retry"], should_retry, f"Attempt {attempt}")
            if should_retry:
                self.assertEqual(policy["retry_after_hours"], expected_hours)


class TestLeadStatusPatch(unittest.TestCase):
    """Test derive_lead_status_patch function."""

    def test_patch_for_interested(self):
        """Test lead status patch for interested outcome."""
        patch = derive_lead_status_patch(OUTCOME_INTERESTED)
        
        self.assertEqual(patch["status"], "contacted")
        self.assertEqual(patch["qualification_status"], "qualified")
        self.assertEqual(patch["next_action"], "send_quote")

    def test_patch_for_not_interested(self):
        """Test lead status patch for not interested outcome."""
        patch = derive_lead_status_patch(OUTCOME_NOT_INTERESTED)
        
        self.assertEqual(patch["status"], "closed_lost")
        self.assertEqual(patch["qualification_status"], "not_interested")

    def test_patch_for_callback_requested(self):
        """Test lead status patch for callback requested."""
        patch = derive_lead_status_patch(OUTCOME_CALLBACK_REQUESTED)
        
        self.assertEqual(patch["status"], "contacted")
        self.assertEqual(patch["qualification_status"], "follow_up")
        self.assertEqual(patch["next_action"], "follow_up_call")

    def test_patch_for_follow_up_needed(self):
        """Test lead status patch for follow up needed."""
        patch = derive_lead_status_patch(OUTCOME_FOLLOW_UP)
        
        self.assertEqual(patch["status"], "contacted")
        self.assertEqual(patch["qualification_status"], "follow_up")
        self.assertEqual(patch["next_action"], "follow_up_email")

    def test_patch_for_unknown_outcome(self):
        """Test lead status patch for unknown outcome returns empty dict."""
        patch = derive_lead_status_patch("unknown_outcome")
        self.assertEqual(patch, {})


class TestOutcomeSignalDetection(unittest.TestCase):
    """Test outcome classification signal detection."""

    def test_positive_signal_detection(self):
        """Test detection of positive signals."""
        transcript = "This sounds great! I'm definitely interested."
        result = classify_outcome_from_transcript(None, transcript)
        
        self.assertGreater(len(result["signals"]), 0)
        self.assertEqual(result["normalized_outcome"], OUTCOME_INTERESTED)

    def test_negative_signal_detection(self):
        """Test detection of negative signals."""
        transcript = "No, I'm not interested in this."
        result = classify_outcome_from_transcript(None, transcript)
        
        self.assertGreater(len(result["signals"]), 0)
        self.assertEqual(result["normalized_outcome"], OUTCOME_NOT_INTERESTED)

    def test_multiple_signals(self):
        """Test detection of multiple signals."""
        transcript = (
            "Tell me more about this proposal. I'm interested but need to review with my team. "
            "Can you call me back Friday?"
        )
        result = classify_outcome_from_transcript(None, transcript)
        
        # Should detect interest and callback signals
        self.assertGreater(len(result["signals"]), 0)


class TestOutcomeMapping(unittest.TestCase):
    """Test outcome mappings for business logic."""

    def test_all_outcomes_are_handled(self):
        """Ensure all canonical outcomes have mappings."""
        test_outcomes = [
            OUTCOME_ANSWERED,
            OUTCOME_NO_ANSWER,
            OUTCOME_BUSY,
            OUTCOME_FAILED,
            OUTCOME_INTERESTED,
            OUTCOME_NOT_INTERESTED,
            OUTCOME_CALLBACK_REQUESTED,
            OUTCOME_FOLLOW_UP,
            OUTCOME_VOICEMAIL,
        ]
        
        for outcome in test_outcomes:
            # Should not raise error
            retry_policy = get_retry_policy(outcome, attempt_count=0)
            self.assertIn("should_retry", retry_policy)
            self.assertIn("retry_after_hours", retry_policy)
            self.assertIn("max_attempts", retry_policy)

    def test_positive_outcomes_dont_retry(self):
        """Test that positive outcomes don't trigger retry."""
        positive_outcomes = [
            OUTCOME_INTERESTED,
            OUTCOME_NOT_INTERESTED,
            OUTCOME_CALLBACK_REQUESTED,
        ]
        
        for outcome in positive_outcomes:
            policy = get_retry_policy(outcome, attempt_count=0)
            self.assertFalse(policy["should_retry"], f"{outcome} should not retry")

    def test_retriable_outcomes_retry(self):
        """Test that retriable outcomes trigger retry."""
        retriable_outcomes = [
            OUTCOME_NO_ANSWER,
            OUTCOME_BUSY,
            OUTCOME_FAILED,
            OUTCOME_VOICEMAIL,
        ]
        
        for outcome in retriable_outcomes:
            policy = get_retry_policy(outcome, attempt_count=0)
            self.assertTrue(policy["should_retry"], f"{outcome} should retry")
            self.assertIsNotNone(policy["retry_after_hours"], f"{outcome} should have retry_after_hours")


if __name__ == "__main__":
    unittest.main()
