"""
Build a fixed LK voice dataset from reviewed transcript CSV/JSONL.

Input:
  audio/lk_transcripts_fixed.csv or audio/lk_transcripts_fixed.jsonl
  audio/my_voice_recordings/normalized/*.wav

Output:
  audio/lk_voice_dataset_fixed/
    wavs/*.wav
    metadata.csv
    metadata.jsonl
    metadata_pipe.csv
    README.txt
  audio/lk_voice_dataset_fixed.zip

Usage from repo root:
  python audio/build_lk_fixed_dataset.py
  python audio/build_lk_fixed_dataset.py --include-mixed
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import wave
import zipfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DEFAULT_CSV = ROOT / "lk_transcripts_fixed.csv"
DEFAULT_JSONL = ROOT / "lk_transcripts_fixed.jsonl"
NORMALIZED_DIR = ROOT / "my_voice_recordings" / "normalized"
OUT_DIR = ROOT / "lk_voice_dataset_fixed"
OUT_WAVS = OUT_DIR / "wavs"
OUT_ZIP = ROOT / "lk_voice_dataset_fixed.zip"

SOURCE_ALIASES = {
    "business_question.wav": "lk_tamil_business_question.wav",
    "emotion.wav": "lk_tamil_emotion.wav",
    "explain.wav": "lk_hindi_explain.wav",
    "expressive.wav": "lk_expressive.wav",
    "expressive1.wav": "lk_hindi_expressive.wav",
    "gags.wav": "lk_bhojpuri_gags.wav",
    "intro.wav": "lk_intro.wav",
    "intro1.wav": "lk_tamil_intro.wav",
    "intro2.wav": "lk_hindi_intro.wav",
    "intro3.wav": "lk_bhojpuri_intro.wav",
    "mixed.wav": "lk_mixed.wav",
    "natural.wav": "lk_natural.wav",
    "number.wav": "lk_number.wav",
    "paragraph.wav": "lk_paragraph.wav",
    "paragraph1.wav": "lk_tamil_paragraph.wav",
    "purchase.wav": "lk_hindi_purchase.wav",
    "start.wav": "lk_start.wav",
    "starting.wav": "lk_hindi_starting.wav",
    "variation.wav": "lk_variation.wav",
}


def read_rows(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def local_audio_for(row: dict) -> Path | None:
    source_name = Path(row.get("source_name") or row.get("source_file") or row.get("audio_path", "")).name
    alias = SOURCE_ALIASES.get(source_name)
    if alias:
        candidate = NORMALIZED_DIR / alias
        if candidate.exists():
            return candidate

    stem = Path(source_name).stem
    language = (row.get("language") or "").lower()
    candidates = [
        NORMALIZED_DIR / f"lk_{stem}.wav",
        NORMALIZED_DIR / f"lk_{language}_{stem}.wav",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        frames = handle.getnframes()
        rate = handle.getframerate()
        return round(frames / float(rate), 2)


def clean_output() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_WAVS.mkdir(parents=True, exist_ok=True)
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()


def write_zip() -> None:
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(OUT_DIR.parent))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=None, help="Reviewed CSV or JSONL. Defaults to CSV if present.")
    parser.add_argument("--include-mixed", action="store_true", help="Include lk_mixed.wav in the fixed dataset.")
    parser.add_argument("--speaker", default="lk")
    args = parser.parse_args()

    input_path = args.input or (DEFAULT_CSV if DEFAULT_CSV.exists() else DEFAULT_JSONL)
    if not input_path.exists():
        raise SystemExit(f"Input not found: {input_path}")

    rows = read_rows(input_path)
    clean_output()

    metadata_rows: list[dict] = []
    skipped: list[tuple[str, str]] = []
    counters = Counter()

    for row in rows:
        source_name = Path(row.get("source_name") or row.get("source_file") or row.get("audio_path", "")).name
        speaker = (row.get("speaker") or "").strip()
        language = (row.get("language") or "").strip().lower()
        text = normalize_text(row.get("text") or row.get("draft_text") or "")

        if speaker != args.speaker:
            skipped.append((source_name, f"speaker is {speaker!r}"))
            continue
        if language == "mixed" and not args.include_mixed:
            skipped.append((source_name, "mixed language excluded"))
            continue
        if not text:
            skipped.append((source_name, "empty text"))
            continue

        src_audio = local_audio_for(row)
        if src_audio is None:
            skipped.append((source_name, "local audio not found"))
            continue

        out_name = f"lk_{len(metadata_rows) + 1:04d}_{src_audio.stem.replace('lk_', '')}.wav"
        dst_audio = OUT_WAVS / out_name
        shutil.copy2(src_audio, dst_audio)

        duration = wav_duration(dst_audio)
        item = {
            "audio_file": f"wavs/{out_name}",
            "speaker": speaker,
            "language": language,
            "duration": duration,
            "text": text,
            "source_name": source_name,
            "source_audio": str(src_audio),
        }
        metadata_rows.append(item)
        counters[language] += 1

    csv_path = OUT_DIR / "metadata.csv"
    jsonl_path = OUT_DIR / "metadata.jsonl"
    pipe_path = OUT_DIR / "metadata_pipe.csv"
    readme_path = OUT_DIR / "README.txt"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["audio_file", "speaker", "language", "duration", "text", "source_name", "source_audio"],
        )
        writer.writeheader()
        writer.writerows(metadata_rows)

    with jsonl_path.open("w", encoding="utf-8") as handle:
        for item in metadata_rows:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    with pipe_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="|")
        for item in metadata_rows:
            wav_id = Path(item["audio_file"]).stem
            writer.writerow([wav_id, item["text"]])

    total_minutes = sum(item["duration"] for item in metadata_rows) / 60.0
    readme = [
        "LK fixed voice dataset",
        "",
        f"Source transcript: {input_path}",
        f"Source audio: {NORMALIZED_DIR}",
        f"Samples: {len(metadata_rows)}",
        f"Total minutes: {total_minutes:.2f}",
        f"Mixed included: {args.include_mixed}",
        "",
        "By language:",
    ]
    for language, count in sorted(counters.items()):
        minutes = sum(item["duration"] for item in metadata_rows if item["language"] == language) / 60.0
        readme.append(f"- {language}: {count} file(s), {minutes:.2f} min")
    if skipped:
        readme.extend(["", "Skipped:"])
        for source_name, reason in skipped:
            readme.append(f"- {source_name}: {reason}")
    readme.extend(
        [
            "",
            "Notes:",
            "- This is a fixed full-recording dataset from reviewed transcripts.",
            "- Long files are preserved as full clips; do not use rough word-ratio splitting for final TTS training.",
            "- For short-clip TTS training, create timestamp-aligned segments from this source of truth.",
        ]
    )
    readme_path.write_text("\n".join(readme) + "\n", encoding="utf-8")

    write_zip()

    print(f"Input rows: {len(rows)}")
    print(f"Written samples: {len(metadata_rows)}")
    print(f"Total minutes: {total_minutes:.2f}")
    print(f"Skipped: {len(skipped)}")
    for language, count in sorted(counters.items()):
        print(f"  {language}: {count}")
    print(f"Dataset: {OUT_DIR}")
    print(f"Zip: {OUT_ZIP}")


if __name__ == "__main__":
    main()
