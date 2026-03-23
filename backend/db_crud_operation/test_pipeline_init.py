import sys
import os
from unittest.mock import MagicMock
from sqlmodel import Session

# Setup path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from pipelines.voice_pipeline import VoicePipeline
from models.models import User

def test_pipeline_init():
    print("Testing VoicePipeline Initialization...")
    
    mock_comm = MagicMock()
    mock_session = MagicMock(spec=Session)
    mock_user = User(id=1, username="testadmin", company_name="Test Co")
    
    # Mock _get_decrypted_integration_keys to return dummy dict
    # This avoids actual DB/Encryption calls
    original_get_keys = VoicePipeline._get_decrypted_integration_keys
    VoicePipeline._get_decrypted_integration_keys = lambda self: {
        "MISTRAL_API_KEY": "test_key",
        "CARTESIA_API_KEY": "test_key",
        "DEEPGRAM_API_KEY": "test_key",
        "MISTRAL_MODEL": "test_model",
        "CARTESIA_VOICE_ID": "test_voice",
        "DEEPGRAM_MODEL": "test_stt_model"
    }
    
    try:
        pipeline = VoicePipeline(
            communicator=mock_comm,
            interaction_id="test_123",
            system_prompt="Hello",
            transcript_accumulator=[],
            session=mock_session,
            user=mock_user,
            llm_provider="mistral",
            tts_provider="cartesia",
            stt_provider="deepgram"
        )
        print("✅ Pipeline initialized successfully!")
    except NameError as e:
        print(f"❌ NameError detected: {e}")
    except Exception as e:
        print(f"❌ Unexpected Error: {type(e).__name__}: {e}")
    finally:
        VoicePipeline._get_decrypted_integration_keys = original_get_keys

if __name__ == "__main__":
    test_pipeline_init()
