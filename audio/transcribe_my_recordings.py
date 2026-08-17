"""
Transcribe prepared voice recordings with WhisperX/faster-whisper.

Input:
  audio/my_voice_recordings/manifest.jsonl
  audio/my_voice_recordings/normalized/*.wav

Output:
  audio/my_voice_recordings/transcripts/*.json
  audio/my_voice_recordings/transcripts/*.txt
  audio/my_voice_recordings/transcripts_manifest.jsonl

Usage from repo root:
  backend\\myenvironment\\Scripts\\python.exe audio\\transcribe_my_recordings.py --model small

Notes:
  - No diarization is used because these are intended to be single-speaker files.
  - Use --limit 1 for a quick smoke test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "my_voice_recordings"
MANIFEST = DATA_DIR / "manifest.jsonl"
TRANSCRIPTS_DIR = DATA_DIR / "transcripts"
OUT_MANIFEST = DATA_DIR / "transcripts_manifest.jsonl"

LANGUAGE_HINTS = {
    "english": "en",
    "hindi": "hi",
    "tamil": "ta",
    "bhojpuri": "hi",
}


def load_manifest() -> list[dict]:
    rows: list[dict] = []
    with MANIFEST.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def language_hint(language: str) -> str | None:
    return LANGUAGE_HINTS.get(language.lower())


def clean_text(segments: list[dict]) -> str:
    parts = [segment.get("text", "").strip() for segment in segments]
    return " ".join(part for part in parts if part).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="small", help="faster-whisper model size: tiny/base/small/medium/large-v3")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--compute_type", default="int8")
    parser.add_argument("--batch_size", type=int, default=8)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--speaker", default="", help="Only transcribe one speaker id, e.g. lk")
    parser.add_argument("--language_filter", default="", help="Only transcribe one manifest language, e.g. english")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    import whisperx

    TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_manifest()
    if args.speaker:
        rows = [row for row in rows if row.get("speaker") == args.speaker]
    if args.language_filter:
        rows = [row for row in rows if row.get("language") == args.language_filter]
    if args.limit:
        rows = rows[: args.limit]

    print(f"Loading WhisperX model: {args.model} ({args.device}, {args.compute_type})")
    model = whisperx.load_model(args.model, args.device, compute_type=args.compute_type)

    output_rows = []

    for index, row in enumerate(rows, start=1):
        audio_path = Path(row["audio_path"])
        stem = audio_path.stem
        json_path = TRANSCRIPTS_DIR / f"{stem}.json"
        txt_path = TRANSCRIPTS_DIR / f"{stem}.txt"

        if json_path.exists() and not args.force:
            result = json.loads(json_path.read_text(encoding="utf-8"))
            text = clean_text(result.get("segments", []))
            print(f"[{index}/{len(rows)}] cached {audio_path.name}")
        else:
            lang = language_hint(row.get("language", ""))
            print(f"[{index}/{len(rows)}] transcribing {audio_path.name} lang={lang or 'auto'}")
            audio = whisperx.load_audio(str(audio_path))
            result = model.transcribe(
                audio,
                batch_size=args.batch_size,
                language=lang,
            )
            text = clean_text(result.get("segments", []))
            payload = {
                "audio_path": str(audio_path),
                "source_path": row.get("source_path"),
                "speaker": row.get("speaker"),
                "language": row.get("language"),
                "duration": row.get("duration"),
                "model": args.model,
                "segments": result.get("segments", []),
                "text": text,
            }
            json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            txt_path.write_text(text + "\n", encoding="utf-8")

        out_row = {
            **row,
            "transcript_json": str(json_path),
            "transcript_txt": str(txt_path),
            "draft_text": text,
        }
        output_rows.append(out_row)

    with OUT_MANIFEST.open("w", encoding="utf-8") as handle:
        for row in output_rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nWrote: {OUT_MANIFEST}")
    print(f"Transcript files: {TRANSCRIPTS_DIR}")


if __name__ == "__main__":
    main()
