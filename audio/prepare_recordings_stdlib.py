"""
Prepare recorded WAV files for voice-cloning experiments using only Python stdlib.

Input:
  audio/recording/**/*.wav

Output:
  audio/my_voice_recordings/normalized/*.wav
  audio/my_voice_recordings/manifest.jsonl
  audio/my_voice_recordings/summary.txt

This script downmixes stereo WAV to mono, trims leading/trailing silence, applies
conservative peak normalization, and preserves the original sample rate.
"""

from __future__ import annotations

import audioop
import json
import math
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parent
INPUT_DIR = ROOT / "recording"
OUT_DIR = ROOT / "my_voice_recordings"
NORMALIZED_DIR = OUT_DIR / "normalized"
MANIFEST = OUT_DIR / "manifest.jsonl"
SUMMARY = OUT_DIR / "summary.txt"

FRAME_MS = 20
TRIM_THRESHOLD_RATIO = 0.012
TARGET_PEAK_RATIO = 0.86


def classify(path: Path) -> tuple[str, str]:
    rel = path.relative_to(INPUT_DIR)
    speaker = rel.parts[0] if rel.parts else "unknown"
    lower_parts = [part.lower() for part in rel.parts]
    language = "english"
    for candidate in ("hindi", "tamil", "bhojpuri"):
        if candidate in lower_parts:
            language = candidate
            break
    if "mixed" in path.stem.lower():
        language = "mixed"
    return speaker, language


def read_wav(path: Path) -> tuple[bytes, int, int]:
    with wave.open(str(path), "rb") as wav:
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        sample_rate = wav.getframerate()
        frames = wav.readframes(wav.getnframes())
    if sample_width != 2:
        raise ValueError(f"Only 16-bit WAV is supported: {path}")
    if channels == 2:
        frames = audioop.tomono(frames, sample_width, 0.5, 0.5)
    elif channels != 1:
        raise ValueError(f"Only mono/stereo WAV is supported: {path}")
    return frames, sample_rate, sample_width


def trim_silence(frames: bytes, sample_rate: int, sample_width: int) -> bytes:
    frame_bytes = int(sample_rate * FRAME_MS / 1000) * sample_width
    if frame_bytes <= 0:
        return frames

    max_peak = audioop.max(frames, sample_width) or 1
    threshold = max(120, int(max_peak * TRIM_THRESHOLD_RATIO))

    chunks = [
        frames[i : i + frame_bytes]
        for i in range(0, len(frames), frame_bytes)
        if len(frames[i : i + frame_bytes]) == frame_bytes
    ]
    if not chunks:
        return frames

    start = 0
    while start < len(chunks) and audioop.rms(chunks[start], sample_width) < threshold:
        start += 1

    end = len(chunks) - 1
    while end > start and audioop.rms(chunks[end], sample_width) < threshold:
        end -= 1

    pad = max(1, int(120 / FRAME_MS))
    start = max(0, start - pad)
    end = min(len(chunks) - 1, end + pad)
    return b"".join(chunks[start : end + 1]) or frames


def peak_normalize(frames: bytes, sample_width: int) -> tuple[bytes, float]:
    peak = audioop.max(frames, sample_width)
    if peak <= 0:
        return frames, 1.0
    max_value = (2 ** (8 * sample_width - 1)) - 1
    target = int(max_value * TARGET_PEAK_RATIO)
    gain = min(target / peak, 4.0)
    return audioop.mul(frames, sample_width, gain), gain


def write_wav(path: Path, frames: bytes, sample_rate: int, sample_width: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(frames)


def seconds(frames: bytes, sample_rate: int, sample_width: int) -> float:
    return len(frames) / sample_width / sample_rate


def dbfs(frames: bytes, sample_width: int) -> float | None:
    rms = audioop.rms(frames, sample_width)
    if rms <= 0:
        return None
    max_value = (2 ** (8 * sample_width - 1)) - 1
    return 20 * math.log10(rms / max_value)


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    NORMALIZED_DIR.mkdir(parents=True, exist_ok=True)

    wavs = sorted(INPUT_DIR.rglob("*.wav"))
    records = []

    for source in wavs:
        speaker, language = classify(source)
        frames, sample_rate, sample_width = read_wav(source)
        original_duration = seconds(frames, sample_rate, sample_width)
        trimmed = trim_silence(frames, sample_rate, sample_width)
        normalized, gain = peak_normalize(trimmed, sample_width)
        output_name = "_".join(source.relative_to(INPUT_DIR).with_suffix("").parts) + ".wav"
        output = NORMALIZED_DIR / output_name
        write_wav(output, normalized, sample_rate, sample_width)

        record = {
            "audio_path": str(output),
            "source_path": str(source),
            "speaker": speaker,
            "language": language,
            "sample_rate": sample_rate,
            "channels": 1,
            "sample_width_bits": sample_width * 8,
            "duration": round(seconds(normalized, sample_rate, sample_width), 3),
            "original_duration": round(original_duration, 3),
            "gain": round(gain, 4),
            "rms_dbfs": None if dbfs(normalized, sample_width) is None else round(dbfs(normalized, sample_width), 2),
            "text": "",
        }
        records.append(record)

    with MANIFEST.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    totals: dict[tuple[str, str], float] = {}
    for record in records:
        key = (record["speaker"], record["language"])
        totals[key] = totals.get(key, 0.0) + record["duration"]

    lines = [
        "Recording preparation summary",
        f"Input: {INPUT_DIR}",
        f"Output: {NORMALIZED_DIR}",
        f"Files: {len(records)}",
        f"Total minutes: {sum(r['duration'] for r in records) / 60:.2f}",
        "",
        "By speaker/language:",
    ]
    for (speaker, language), duration in sorted(totals.items()):
        lines.append(f"- {speaker}/{language}: {duration / 60:.2f} min")

    lines.extend(
        [
            "",
            "Notes:",
            "- MPEG/M4A/MP3 files are not processed by this stdlib script.",
            "- Transcripts are intentionally blank; fill them after transcription/review.",
            "- Sample rate is preserved because stdlib has no high-quality resampler.",
        ]
    )
    SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(SUMMARY.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
