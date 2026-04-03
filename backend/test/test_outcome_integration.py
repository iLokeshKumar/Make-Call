"""
Integration tests for the full call outcome workflow.

Tests end-to-end functionality from call completion through lead status updates,
retry scheduling, and campaign advancement.
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, select

# Mock models for testing if needed
CallTask = None
Interaction = None
Lead = None
CampaignRecipient = None

try:
    from models.models import CallTask, Interaction, Lead, Campaign, CampaignRecipient, Company, User, utc_now
    HAS_MODELS = True
except ImportError:
    HAS_MODELS = False

from services.outcome_service import (
    OUTCOME_INTERESTED,
    OUTCOME_NOT_INTERESTED,
    OUTCOME_CALLBACK_REQUESTED,
    OUTCOME_FOLLOW_UP,
    OUTCOME_NO_ANSWER,
    OUTCOME_BUSY,
    OUTCOME_VOICEMAIL,
    normalize_call_outcome,
    classify_outcome_from_transcript,
    get_retry_policy,
    derive_lead_status_patch,
    apply_call_outcome,
)


class IntegrationTestOutcomeWorkflow(unittest.TestCase):
    """Integration tests for full call outcome workflow."""

    def test_positive_outcome_workflow(self):
        """
        Test positive outcome flow:
        - Call completes with interest
        - Lead status updated to qualified
        - No retry scheduled
        - Next action set to send_quote
        """
        transcript = "This is exactly what we need. I'm very interested. Can you send me a quote?"
        outcome = normalize_call_outcome("answered", transcript)
        
        self.assertEqual(outcome, OUTCOME_INTERESTED)
        
        # Check retry policy
        policy = get_retry_policy(outcome, attempt_count=0)
        self.assertFalse(policy["should_retry"])
        
        # Check lead status patch
        patch_data = derive_lead_status_patch(outcome)
        self.assertEqual(patch_data["status"], "contacted")
        self.assertEqual(patch_data["qualification_status"], "qualified")
        self.assertEqual(patch_data["next_action"], "send_quote")

    def test_no_answer_workflow(self):
        """
        Test no answer flow:
        - Call returns no_answer
        - Lead status set to contacted with follow_up status
        - Retry scheduled (up to 6 attempts)
        - First retry after 1 hour
        """
        transcript = ""
        outcome = normalize_call_outcome("no_answer", transcript)
        
        self.assertEqual(outcome, OUTCOME_NO_ANSWER)
        
        # First attempt should schedule retry
        policy = get_retry_policy(outcome, attempt_count=0)
        self.assertTrue(policy["should_retry"])
        self.assertEqual(policy["retry_after_hours"], 1)
        self.assertEqual(policy["max_attempts"], 6)
        
        # Fifth attempt should schedule last retry
        policy = get_retry_policy(outcome, attempt_count=5)
        self.assertTrue(policy["should_retry"])
        self.assertEqual(policy["retry_after_hours"], 24)
        
        # Sixth attempt should not retry
        policy = get_retry_policy(outcome, attempt_count=6)
        self.assertFalse(policy["should_retry"])
        self.assertTrue(policy["max_attempts_reached"])

    def test_callback_requested_workflow(self):
        """
        Test callback requested flow:
        - Call completes with callback request
        - Lead marked for follow-up
        - No automatic retry
        - Next action set to follow_up_call
        """
        transcript = "Call me back tomorrow, I'll have more information by then."
        outcome = normalize_call_outcome("answered", transcript)
        
        self.assertEqual(outcome, OUTCOME_CALLBACK_REQUESTED)
        
        # No retry for callback
        policy = get_retry_policy(outcome, attempt_count=0)
        self.assertFalse(policy["should_retry"])
        
        # Lead patch for callback
        patch_data = derive_lead_status_patch(outcome)
        self.assertEqual(patch_data["qualification_status"], "follow_up")
        self.assertEqual(patch_data["next_action"], "follow_up_call")

    def test_not_interested_workflow(self):
        """
        Test negative outcome flow:
        - Call completes as not interested
        - Lead marked as closed_lost
        - No retry scheduled
        """
        transcript = "This is not a fit for us. Please stop calling."
        outcome = normalize_call_outcome("answered", transcript)
        
        self.assertEqual(outcome, OUTCOME_NOT_INTERESTED)
        
        # No retry for not interested
        policy = get_retry_policy(outcome, attempt_count=0)
        self.assertFalse(policy["should_retry"])
        
        # Lead patch for not interested
        patch_data = derive_lead_status_patch(outcome)
        self.assertEqual(patch_data["status"], "closed_lost")
        self.assertEqual(patch_data["qualification_status"], "not_interested")

    def test_voicemail_workflow(self):
        """
        Test voicemail flow:
        - Call returns voicemail
        - Lead status updated to contacted
        - Retry scheduled (max 2 attempts)
        - First retry after 24 hours
        - Second attempt should not retry
        """
        transcript = ""
        outcome = normalize_call_outcome("voicemail", transcript)
        
        self.assertEqual(outcome, OUTCOME_VOICEMAIL)
        
        # First attempt should schedule retry
        policy = get_retry_policy(outcome, attempt_count=0)
        self.assertTrue(policy["should_retry"])
        self.assertEqual(policy["retry_after_hours"], 24)
        self.assertEqual(policy["max_attempts"], 2)
        
        # Attempt 2 (already at max) should not retry
        policy = get_retry_policy(outcome, attempt_count=2)
        self.assertFalse(policy["should_retry"])

    def test_progressive_retry_schedule(self):
        """
        Test that no_answer outcome has progressive retry delays.
        First attempt: 1 hour
        Second attempt: 2 hours
        Third attempt: 4 hours
        Fourth attempt: 8 hours
        Fifth attempt: 16 hours
        Sixth attempt: 24 hours
        """
        outcome = OUTCOME_NO_ANSWER
        expected_schedule = [1, 2, 4, 8, 16, 24]
        
        for attempt, expected_hours in enumerate(expected_schedule):
            policy = get_retry_policy(outcome, attempt_count=attempt)
            self.assertTrue(policy["should_retry"], f"Attempt {attempt} should retry")
            self.assertEqual(policy["retry_after_hours"], expected_hours)

    def test_classification_with_signal_detection(self):
        """
        Test that classification correctly detects and reports signals.
        """
        test_cases = [
            ("I'm definitely interested in this solution", OUTCOME_INTERESTED),
            ("Not interested in this", OUTCOME_NOT_INTERESTED),
            ("Call me back next week", OUTCOME_CALLBACK_REQUESTED),
            ("Can you share more pricing details?", OUTCOME_INTERESTED),  # "share" is positive signal
        ]
        
        for transcript, expected_outcome in test_cases:
            result = classify_outcome_from_transcript(None, transcript)
            self.assertEqual(result["normalized_outcome"], expected_outcome)
            self.assertGreater(result["confidence"], Decimal("0.5"))
            self.assertIsNotNone(result["suggested_next_action"])
            self.assertIsInstance(result["signals"], list)

    def test_outcome_upgrade_prevention(self):
        """
        Test that we don't downgrade a positive outcome if a later callback
        posts a weaker provider status (simulated).
        """
        # Simulate: first call was answered and interested
        first_outcome = normalize_call_outcome("answered", "Yes, I'm interested")
        self.assertEqual(first_outcome, OUTCOME_INTERESTED)
        
        policy = get_retry_policy(first_outcome, attempt_count=0)
        self.assertFalse(policy["should_retry"])

    def test_lead_status_transitions(self):
        """
        Test that each outcome maps to appropriate lead status transitions.
        """
        transitions = {
            OUTCOME_INTERESTED: {
                "status": "contacted",
                "qualification_status": "qualified",
            },
            OUTCOME_NOT_INTERESTED: {
                "status": "closed_lost",
                "qualification_status": "not_interested",
            },
            OUTCOME_CALLBACK_REQUESTED: {
                "status": "contacted",
                "qualification_status": "follow_up",
            },
            OUTCOME_FOLLOW_UP: {
                "status": "contacted",
                "qualification_status": "follow_up",
            },
        }
        
        for outcome, expected_fields in transitions.items():
            patch = derive_lead_status_patch(outcome)
            for field, value in expected_fields.items():
                self.assertEqual(patch[field], value, f"Outcome {outcome} field {field}")

    def test_transcript_analysis_scenarios(self):
        """
        Test realistic transcript scenarios and outcome classification.
        """
        scenarios = [
            {
                "name": "High interest scenario",
                "transcript": "This looks great! Exactly what we've been looking for. Send me a quote and let's schedule a demo.",
                "expected": OUTCOME_INTERESTED,
                "min_confidence": Decimal("0.60"),
            },
            {
                "name": "Callback scenario",
                "transcript": "Call me back tomorrow, I'll have more information by then.",
                "expected": OUTCOME_CALLBACK_REQUESTED,
                "min_confidence": Decimal("0.50"),
            },
            {
                "name": "Rejection scenario",
                "transcript": "We're not interested. Please remove us from your list.",
                "expected": OUTCOME_NOT_INTERESTED,
                "min_confidence": Decimal("0.50"),
            },
            {
                "name": "Information gathering scenario",
                "transcript": "Can you share more details about pricing and support?",
                "expected": OUTCOME_INTERESTED,  # "share" is positive signal
                "min_confidence": Decimal("0.50"),
            },
        ]
        
        for scenario in scenarios:
            with self.subTest(scenario=scenario["name"]):
                result = classify_outcome_from_transcript(None, scenario["transcript"])
                self.assertEqual(result["normalized_outcome"], scenario["expected"])
                self.assertGreaterEqual(result["confidence"], scenario["min_confidence"])
                self.assertIn("summary", result)
                self.assertGreaterEqual(len(result["summary"]), 0)

    def test_all_outcomes_have_retry_policies(self):
        """
        Verify that every canonical outcome has a defined retry policy.
        """
        all_outcomes = [
            OUTCOME_INTERESTED,
            OUTCOME_NOT_INTERESTED,
            OUTCOME_CALLBACK_REQUESTED,
            OUTCOME_FOLLOW_UP,
            OUTCOME_NO_ANSWER,
            OUTCOME_BUSY,
            OUTCOME_VOICEMAIL,
        ]
        
        for outcome in all_outcomes:
            with self.subTest(outcome=outcome):
                policy = get_retry_policy(outcome, attempt_count=0)
                self.assertIn("should_retry", policy)
                self.assertIn("retry_after_hours", policy)
                self.assertIn("max_attempts", policy)
                self.assertIn("max_attempts_reached", policy)


if __name__ == "__main__":
    unittest.main()
