def test_merge_segments_multiple_lines():
    from pipelines.voice.transcript_manager import _map_segments_to_lines
    # Simulate provider segments that should map to two transcript lines
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello how are"},
        {"start": 1.0, "end": 2.0, "text": "you doing today"},
    ]
    transcript_lines = ["hello how are you", "doing today"]

    mapped = _map_segments_to_lines(segments, transcript_lines, overlap_threshold=0.5)
    assert len(mapped) == 2


def test_speaker_diarization_interleaved():
    from pipelines.voice.transcript_manager import _map_segments_to_lines
    # Interleaved speaker segments — mapping should keep chronology
    segments = [
        {"start": 0.0, "end": 0.5, "text": "agent hello"},
        {"start": 0.5, "end": 1.2, "text": "customer hi"},
        {"start": 1.2, "end": 2.0, "text": "agent how can I help"},
    ]
    transcript_lines = ["agent: hello", "customer: hi", "agent: how can I help"]
    mapped = _map_segments_to_lines(segments, transcript_lines, overlap_threshold=0.5)
    assert len(mapped) == 3


def test_provider_shape_variations():
    from pipelines.voice.transcript_manager import _normalize_provider_segments
    # Provider A uses segments + words array
    provider_a = {"segments": [{"start":0.0, "end":0.5, "text":"hi there"}], "words": [{"text":"hi","start":0.0,"end":0.2},{"text":"there","start":0.2,"end":0.5}]} 
    normalized = _normalize_provider_segments(provider_a)
    assert isinstance(normalized, list)
