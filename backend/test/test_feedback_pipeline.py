import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from sqlmodel import Session
from services.call.post_call_service import extract_and_save_requirements

@pytest.mark.asyncio
async def test_feedback_saved_on_llm_failure():
    """
    Verifies that verbal feedback is captured via regex fallback and CSAT is triggered
    even if the LLM returns malformed JSON for lead requirements.
    """
    # Mock LLM to return invalid JSON
    llm_service = MagicMock()
    
    # Simulate a stream that returns invalid JSON
    async def mock_stream():
        yield {"type": "token", "content": "I am not JSON"}
        yield {"type": "finished", "full_reply": "I am not JSON"}
    
    llm_service.stream = mock_stream

    # Mock DB session
    session = MagicMock(spec=Session)
    session.exec = MagicMock()
    session.exec().first.return_value = None # No existing feedback

    # Transcript with a clear rating
    transcript = "Rio: How would you rate me?\nUser: I'd say a 4 because you were helpful."

    # Mock external service calls to avoid side effects/imports
    with patch("services.call.post_call_service.upsert_lead_requirements") as mock_upsert, \
         patch("services.objection_service.extract_and_save_objections", new_callable=AsyncMock), \
         patch("services.call.call_coach_service.score_call_and_coach", new_callable=AsyncMock), \
         patch("services.feedback.auto_csat_service.maybe_send_auto_csat") as mock_csat, \
         patch("agents.orchestrator.run_post_call", new_callable=AsyncMock), \
         patch("agents.post_call_nurture.EmailWriter.send_personalized_followup"):

        
        # Run the function
        # Note: we ignore the 'saved' return value since we expect it to be None
        await extract_and_save_requirements(
            session=session,
            llm_service=llm_service,
            company_id=1,
            actor_user_id=1,
            interaction_id=123,
            lead_id=456,
            transcript=transcript
        )

        # Assertions
        
        # 1. upsert_lead_requirements was NOT called (because structured was empty)
        mock_upsert.assert_not_called()
        
        # 2. session.add was called for Feedback
        # We check the attributes of the added objects
        feedback_added = False
        for call in session.add.call_args_list:
            obj = call[0][0]
            # Check if it's a Feedback object by checking its class name or common attributes
            if obj.__class__.__name__ == "Feedback" or (hasattr(obj, 'rating') and hasattr(obj, 'feedback_type') and getattr(obj, 'feedback_type') == "csat"):
                assert obj.rating == 4
                assert "helpful" in obj.comment.lower()
                feedback_added = True
        
        assert feedback_added, "Feedback should have been added via regex fallback even if LLM failed"
        
        # 3. CSAT was triggered (Decoupling proof)
        # It should be called with answered_general since qual was not extracted
        mock_csat.assert_called_once()
        args, kwargs = mock_csat.call_args
        assert kwargs['normalized_outcome'] == "answered_general"

@pytest.mark.asyncio
async def test_feedback_saved_on_llm_success():
    """
    Verifies that when LLM returns valid JSON, it is used, but we still have fallback safety.
    """
    # Mock LLM to return valid JSON
    llm_service = MagicMock()
    
    import json
    valid_json = {
        "verbal_rating": 5,
        "verbal_comment": "Excellent service!",
        "qualification_status": "qualified",
        "next_action": "follow_up_email"
    }
    
    async def mock_stream():
        yield {"type": "finished", "full_reply": json.dumps(valid_json)}
    
    llm_service.stream = mock_stream

    # Mock DB session
    session = MagicMock(spec=Session)
    session.exec = MagicMock()
    session.exec().first.return_value = None

    transcript = "User: You are great, 5 stars."

    with patch("services.call.post_call_service.upsert_lead_requirements") as mock_upsert, \
         patch("services.objection_service.extract_and_save_objections", new_callable=AsyncMock), \
         patch("services.call.call_coach_service.score_call_and_coach", new_callable=AsyncMock), \
         patch("services.feedback.auto_csat_service.maybe_send_auto_csat") as mock_csat, \
         patch("agents.orchestrator.run_post_call", new_callable=AsyncMock), \
         patch("agents.post_call_nurture.EmailWriter.send_personalized_followup"):

        
        await extract_and_save_requirements(
            session=session,
            llm_service=llm_service,
            company_id=1,
            actor_user_id=1,
            interaction_id=123,
            lead_id=456,
            transcript=transcript
        )

        # 1. upsert_lead_requirements WAS called
        mock_upsert.assert_called_once()
        
        # 2. Feedback was saved with LLM values
        feedback_added = False
        for call in session.add.call_args_list:
            obj = call[0][0]
            if hasattr(obj, 'rating') and hasattr(obj, 'feedback_type') and obj.feedback_type == "csat":
                assert obj.rating == 5
                assert "excellent" in obj.comment.lower()
                feedback_added = True
        assert feedback_added

        # 3. CSAT was triggered with correct outcome
        mock_csat.assert_called_once()
        args, kwargs = mock_csat.call_args
        assert kwargs['normalized_outcome'] == "answered_interested"
