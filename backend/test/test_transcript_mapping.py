import json
from sqlmodel import Session, select
from database import engine, init_db
from utils import settings_cache as _sc
from models.models import Interaction, ASRSegment
from pipelines.voice.transcript_manager import TranscriptManager


def setup_module():
    # Ensure DB tables exist in in-memory sqlite for tests
    init_db()


def test_mapping_and_hashing():
    # Company id 1
    company_id = 1
    # Ensure company-scoped setting is off (default: hashed)
    _sc.set_val("ASR_STORE_RAW_JSON", "0", user_id=company_id)
    _sc.set_val("ASR_OVERLAP_THRESHOLD", "0.5", user_id=company_id)

    with Session(engine) as session:
        # Create a minimal interaction
        i = Interaction(company_id=company_id, user_id=1, type="call", content="Test", transcript="")
        session.add(i)
        session.commit()
        session.refresh(i)

        tm = TranscriptManager(str(i.id), session)
        # Simulate a single user line
        tm.transcript_accumulator = ["User: Hello world"]
        # Two raw segments from provider
        tm.asr_segments = [
            {"start": 0.2, "end": 0.8, "text": "Hello", "raw": [{"word": "Hello", "start": 0.2, "end": 0.5}]},
            {"start": 0.9, "end": 1.4, "text": "world", "raw": [{"word": "world", "start": 0.9, "end": 1.2}]},
        ]
        # Save transcript — should map and persist one row for the single user line
        tm.save_transcript()

        rows = session.exec(select(ASRSegment).where(ASRSegment.interaction_id == i.id)).all()
        assert len(rows) == 1
        row = rows[0]
        assert row.text is not None
        # word_json should contain a hash by default
        assert isinstance(row.word_json, dict)
        assert "hash" in row.word_json

        # Clean up
        session.delete(row)
        session.delete(i)
        session.commit()
