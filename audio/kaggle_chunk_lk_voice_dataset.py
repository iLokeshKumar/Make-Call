"""
Kaggle script: split lk_voice_dataset_fixed.zip into short TTS clips.

Assumed Kaggle input:
  /kaggle/input/datasets/lokeshk431/lkvoice/lk_voice_dataset_fixed.zip

Output:
  /kaggle/working/lk_voice_dataset_chunks/
    wavs/*.wav
    metadata.csv
    metadata.jsonl
    metadata_pipe.csv
    review.csv
    README.txt
  /kaggle/working/lk_voice_dataset_chunks.zip

Recommended Kaggle setup:
  Accelerator: GPU T4 if available, CPU also works but transcription is slower.
  Internet: On for first dependency/model download.

Run in a Kaggle notebook:
  !python /kaggle/working/kaggle_chunk_lk_voice_dataset.py
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
import wave
import zipfile
from pathlib import Path


INPUT_DATASET_DIRS = [
    Path("/kaggle/input/lkvoice"),
    Path("/kaggle/input/datasets/lokeshk431/lkvoice"),
    Path("/kaggle/input/lk-voice"),
    Path("/kaggle/input/lkvoice1"),
    Path("/kaggle/input/datasets/lokeshk431/lkvoice1"),
]
WORK_ROOT = Path("/kaggle/working/lk_voice_chunk_work")
EXTRACT_DIR = WORK_ROOT / "extracted"
OUT_DIR = Path("/kaggle/working/lk_voice_dataset_chunks")
OUT_WAVS = OUT_DIR / "wavs"
OUT_ZIP = Path("/kaggle/working/lk_voice_dataset_chunks.zip")

TARGET_SR = 24000
MIN_CHUNK_SEC = 3.0
MAX_CHUNK_SEC = 18.0
SOFT_CHUNK_SEC = 12.0
SILENCE_DB = -40
MIN_SILENCE_SEC = 0.35
PADDING_SEC = 0.08

LANGUAGE_HINTS = {
    "english": "en",
    "hindi": "hi",
    "tamil": "ta",
    # Bhojpuri support is weak in most ASR models; Hindi hint is usually better than auto.
    "bhojpuri": "hi",
}


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def find_zip() -> Path | None:
    candidates = []
    for input_dir in INPUT_DATASET_DIRS:
        if input_dir.exists():
            candidates.extend(input_dir.rglob("*.zip"))
    if not candidates and Path("/kaggle/input").exists():
        candidates = list(Path("/kaggle/input").rglob("lk_voice_dataset*.zip"))
    if not candidates:
        return None
    print("Using zip:", candidates[0])
    return candidates[0]


def extract_dataset() -> Path:
    ensure_clean_dir(EXTRACT_DIR)
    zip_path = find_zip()
    if zip_path is not None:
        with zipfile.ZipFile(zip_path, "r") as archive:
            archive.extractall(EXTRACT_DIR)
    else:
        print("No zip found. Looking for already-extracted metadata under /kaggle/input...")
        direct_metadata = []
        for input_dir in INPUT_DATASET_DIRS:
            if input_dir.exists():
                direct_metadata.extend(input_dir.rglob("metadata.jsonl"))
                direct_metadata.extend(input_dir.rglob("metadata.csv"))
        if not direct_metadata and Path("/kaggle/input").exists():
            direct_metadata = sorted(Path("/kaggle/input").rglob("metadata.jsonl"))
        if not direct_metadata:
            direct_metadata = sorted(Path("/kaggle/input").rglob("metadata.csv"))
        if direct_metadata:
            print("Using extracted dataset metadata:", direct_metadata[0])
            return direct_metadata[0]
        raise FileNotFoundError(
            "Could not find a zip or extracted metadata.csv/metadata.jsonl under /kaggle/input. "
            "Run: !find /kaggle/input -maxdepth 6 -type f | sort | head -100"
        )
    metadata = sorted(EXTRACT_DIR.rglob("metadata.jsonl"))
    if metadata:
        return metadata[0]
    metadata_csv = sorted(EXTRACT_DIR.rglob("metadata.csv"))
    if metadata_csv:
        return metadata_csv[0]
    raise FileNotFoundError("No metadata.jsonl or metadata.csv found inside uploaded zip")


def load_metadata(path: Path) -> list[dict]:
    if path.suffix.lower() == ".jsonl":
        rows = []
        with path.open("r", encoding="utf-8-sig") as handle:
            for line in handle:
                if line.strip():
                    rows.append(json.loads(line))
        return rows
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def source_wav(row: dict, metadata_path: Path) -> Path:
    rel = row["audio_file"]
    candidate = metadata_path.parent / rel
    if candidate.exists():
        return candidate
    matches = sorted(EXTRACT_DIR.rglob(Path(rel).name))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Missing wav for {rel}")


def wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def ffmpeg_convert(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(TARGET_SR),
            "-sample_fmt",
            "s16",
            str(dst),
        ]
    )


def detect_silences(path: Path) -> list[tuple[float, float]]:
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={SILENCE_DB}dB:d={MIN_SILENCE_SEC}",
        "-f",
        "null",
        "-",
    ]
    proc = subprocess.run(cmd, text=True, capture_output=True)
    text = proc.stderr
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", text)]
    return list(zip(starts, ends))


def split_ranges(duration: float, silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    # Candidate breakpoints are silence midpoints. Build chunks up to SOFT_CHUNK_SEC,
    # but never longer than MAX_CHUNK_SEC unless there is no usable silence.
    breakpoints = [0.0]
    breakpoints.extend((start + end) / 2 for start, end in silences if 0 < start < duration)
    breakpoints.append(duration)
    breakpoints = sorted(set(round(x, 3) for x in breakpoints))

    ranges: list[tuple[float, float]] = []
    start = 0.0
    while start < duration - 0.1:
        target = min(start + SOFT_CHUNK_SEC, duration)
        hard = min(start + MAX_CHUNK_SEC, duration)
        candidates = [bp for bp in breakpoints if start + MIN_CHUNK_SEC <= bp <= hard]
        if candidates:
            before_target = [bp for bp in candidates if bp <= target]
            end = before_target[-1] if before_target else candidates[0]
        else:
            end = hard
        if end - start < MIN_CHUNK_SEC:
            break
        ranges.append((max(0.0, start - PADDING_SEC), min(duration, end + PADDING_SEC)))
        start = end
    return ranges


def slice_wav(src: Path, dst: Path, start: float, end: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            str(TARGET_SR),
            "-sample_fmt",
            "s16",
            str(dst),
        ]
    )


def transcribe_chunks(rows: list[dict]) -> list[dict]:
    from faster_whisper import WhisperModel

    device = "cuda" if shutil.which("nvidia-smi") else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"
    print(f"Loading faster-whisper small on {device}/{compute_type}")
    model = WhisperModel("small", device=device, compute_type=compute_type)

    output = []
    for index, row in enumerate(rows, start=1):
        language = row["language"]
        hint = LANGUAGE_HINTS.get(language)
        print(f"[{index}/{len(rows)}] ASR {row['audio_file']} lang={hint or 'auto'}")
        segments, info = model.transcribe(
            str(OUT_DIR / row["audio_file"]),
            language=hint,
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        item = {
            **row,
            "text": " ".join(text.split()),
            "asr_language": getattr(info, "language", ""),
            "asr_language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
        }
        output.append(item)
    return output


def write_outputs(rows: list[dict], skipped: list[dict]) -> None:
    metadata_csv = OUT_DIR / "metadata.csv"
    metadata_jsonl = OUT_DIR / "metadata.jsonl"
    metadata_pipe = OUT_DIR / "metadata_pipe.csv"
    review_csv = OUT_DIR / "review.csv"

    fields = [
        "audio_file",
        "speaker",
        "language",
        "duration",
        "text",
        "source_audio_file",
        "source_start",
        "source_end",
        "source_text",
        "asr_language",
        "asr_language_probability",
    ]

    with metadata_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with metadata_jsonl.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with metadata_pipe.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="|")
        for row in rows:
            writer.writerow([Path(row["audio_file"]).stem, row["text"]])

    review_fields = fields + ["keep", "notes"]
    with review_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=review_fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "keep": "", "notes": ""})

    total_minutes = sum(float(row["duration"]) for row in rows) / 60.0
    by_language: dict[str, list[float]] = {}
    for row in rows:
        by_language.setdefault(row["language"], []).append(float(row["duration"]))

    readme = [
        "LK short-clip dataset generated on Kaggle",
        "",
        f"Samples: {len(rows)}",
        f"Total minutes: {total_minutes:.2f}",
        f"Target sample rate: {TARGET_SR}",
        f"Chunk length target: {MIN_CHUNK_SEC}-{MAX_CHUNK_SEC} sec",
        "",
        "By language:",
    ]
    for language, durations in sorted(by_language.items()):
        readme.append(f"- {language}: {len(durations)} clips, {sum(durations) / 60.0:.2f} min")
    readme.extend(
        [
            "",
            "Important:",
            "- Chunk text is generated by faster-whisper per clip.",
            "- Review review.csv before using this for final TTS fine-tuning.",
            "- Delete clips with wrong text, silence, repeated words, or bad pronunciation.",
        ]
    )
    if skipped:
        readme.extend(["", "Skipped:"])
        for item in skipped:
            readme.append(f"- {item}")
    (OUT_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(OUT_DIR.parent))


def main() -> None:
    ensure_clean_dir(WORK_ROOT)
    ensure_clean_dir(OUT_DIR)
    OUT_WAVS.mkdir(parents=True, exist_ok=True)

    metadata_path = extract_dataset()
    input_rows = load_metadata(metadata_path)
    print("Metadata:", metadata_path)
    print("Input rows:", len(input_rows))

    chunk_rows: list[dict] = []
    skipped: list[dict] = []

    converted_dir = WORK_ROOT / "converted"
    converted_dir.mkdir(parents=True, exist_ok=True)

    for row_index, row in enumerate(input_rows, start=1):
        try:
            src = source_wav(row, metadata_path)
            converted = converted_dir / src.name
            ffmpeg_convert(src, converted)
            duration = wav_duration(converted)
            silences = detect_silences(converted)
            ranges = split_ranges(duration, silences)
            print(f"[{row_index}/{len(input_rows)}] {src.name}: {duration:.1f}s -> {len(ranges)} chunks")

            for chunk_index, (start, end) in enumerate(ranges, start=1):
                out_name = f"{Path(row['audio_file']).stem}_{chunk_index:03d}.wav"
                out_path = OUT_WAVS / out_name
                slice_wav(converted, out_path, start, end)
                actual_duration = round(wav_duration(out_path), 2)
                if actual_duration < MIN_CHUNK_SEC:
                    out_path.unlink(missing_ok=True)
                    continue
                chunk_rows.append(
                    {
                        "audio_file": f"wavs/{out_name}",
                        "speaker": row.get("speaker", "lk"),
                        "language": row.get("language", ""),
                        "duration": actual_duration,
                        "text": "",
                        "source_audio_file": row.get("audio_file", src.name),
                        "source_start": round(start, 3),
                        "source_end": round(end, 3),
                        "source_text": row.get("text", ""),
                    }
                )
        except Exception as exc:
            skipped.append({"row": row_index, "audio_file": row.get("audio_file"), "error": str(exc)})
            print("SKIP:", skipped[-1])

    print("Chunks before ASR:", len(chunk_rows))
    chunk_rows = transcribe_chunks(chunk_rows)
    chunk_rows = [row for row in chunk_rows if row["text"].strip()]
    print("Chunks after ASR text filter:", len(chunk_rows))

    write_outputs(chunk_rows, skipped)
    print("Done")
    print("Output folder:", OUT_DIR)
    print("Output zip:", OUT_ZIP)


if __name__ == "__main__":
    main()
