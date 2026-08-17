"""
Google Colab script: chunk LK voice dataset from a Google Drive file.

Input Drive file:
  https://drive.google.com/file/d/1UVPWukULhkYgv2rk81zWJoe_kIurnpJZ/view

Output in Drive:
  /content/drive/MyDrive/rio_voice/output/lk_voice_dataset_chunks.zip
  /content/drive/MyDrive/rio_voice/output/lk_voice_dataset_chunks/

Usage in Colab:
  1. Mount Drive.
  2. Install faster-whisper.
  3. Paste/run this script.
"""

from __future__ import annotations

import csv
import json
import re
import shutil
import subprocess
import wave
import zipfile
from pathlib import Path


DRIVE_FILE_ID = "1UVPWukULhkYgv2rk81zWJoe_kIurnpJZ"

WORK_ROOT = Path("/content/lk_voice_chunk_work")
INPUT_ZIP = WORK_ROOT / "lk_voice_dataset_fixed.zip"
EXTRACT_DIR = WORK_ROOT / "extracted"
OUT_DIR = Path("/content/lk_voice_dataset_chunks")
OUT_WAVS = OUT_DIR / "wavs"

DRIVE_OUT = Path("/content/drive/MyDrive/rio_voice/output")
DRIVE_OUT_ZIP = DRIVE_OUT / "lk_voice_dataset_chunks.zip"
DRIVE_OUT_FOLDER = DRIVE_OUT / "lk_voice_dataset_chunks"

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
    "bhojpuri": "hi",
}


def run(cmd: list[str]) -> str:
    result = subprocess.run(cmd, check=True, text=True, capture_output=True)
    return result.stdout.strip()


def ensure_clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def download_drive_file() -> None:
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    if INPUT_ZIP.exists() and INPUT_ZIP.stat().st_size > 10_000_000:
        print("Using existing input zip:", INPUT_ZIP)
        return

    try:
        import gdown
    except ImportError as exc:
        raise RuntimeError("Install gdown first: !pip install -q gdown") from exc

    url = f"https://drive.google.com/uc?id={DRIVE_FILE_ID}"
    print("Downloading Drive file:", url)
    gdown.download(url, str(INPUT_ZIP), quiet=False, fuzzy=True)
    if not INPUT_ZIP.exists() or INPUT_ZIP.stat().st_size < 10_000_000:
        raise RuntimeError(
            "Drive download failed or file is too small. In Drive, set sharing to "
            "'Anyone with the link can view', then rerun."
        )
    print("Downloaded:", INPUT_ZIP, INPUT_ZIP.stat().st_size)


def extract_dataset() -> Path:
    ensure_clean_dir(EXTRACT_DIR)
    with zipfile.ZipFile(INPUT_ZIP, "r") as archive:
        archive.extractall(EXTRACT_DIR)

    metadata = sorted(EXTRACT_DIR.rglob("metadata.jsonl"))
    if metadata:
        return metadata[0]
    metadata_csv = sorted(EXTRACT_DIR.rglob("metadata.csv"))
    if metadata_csv:
        return metadata_csv[0]
    raise FileNotFoundError("No metadata.jsonl or metadata.csv found inside input zip")


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
    breakpoints = [0.0]
    breakpoints.extend((start + end) / 2 for start, end in silences if 0 < start < duration)
    breakpoints.append(duration)
    breakpoints = sorted(set(round(x, 3) for x in breakpoints))

    ranges = []
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
        hint = LANGUAGE_HINTS.get(row["language"])
        print(f"[{index}/{len(rows)}] ASR {row['audio_file']} lang={hint or 'auto'}")
        segments, info = model.transcribe(
            str(OUT_DIR / row["audio_file"]),
            language=hint,
            vad_filter=True,
            beam_size=5,
        )
        text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())
        output.append(
            {
                **row,
                "text": " ".join(text.split()),
                "asr_language": getattr(info, "language", ""),
                "asr_language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
            }
        )
    return output


def write_outputs(rows: list[dict], skipped: list[dict]) -> None:
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

    with (OUT_DIR / "metadata.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with (OUT_DIR / "metadata.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    with (OUT_DIR / "metadata_pipe.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="|")
        for row in rows:
            writer.writerow([Path(row["audio_file"]).stem, row["text"]])

    with (OUT_DIR / "review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields + ["keep", "notes"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "keep": "", "notes": ""})

    total_minutes = sum(float(row["duration"]) for row in rows) / 60.0
    readme = [
        "LK short-clip dataset generated on Colab",
        "",
        f"Samples: {len(rows)}",
        f"Total minutes: {total_minutes:.2f}",
        f"Target sample rate: {TARGET_SR}",
        f"Chunk length target: {MIN_CHUNK_SEC}-{MAX_CHUNK_SEC} sec",
        "",
        "Important:",
        "- Chunk text is generated by faster-whisper per clip.",
        "- Review review.csv before final TTS fine-tuning.",
    ]
    if skipped:
        readme.extend(["", "Skipped:"])
        readme.extend(str(item) for item in skipped)
    (OUT_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    local_zip = Path("/content/lk_voice_dataset_chunks.zip")
    if local_zip.exists():
        local_zip.unlink()
    with zipfile.ZipFile(local_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(OUT_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(OUT_DIR.parent))

    DRIVE_OUT.mkdir(parents=True, exist_ok=True)
    shutil.copy2(local_zip, DRIVE_OUT_ZIP)
    if DRIVE_OUT_FOLDER.exists():
        shutil.rmtree(DRIVE_OUT_FOLDER)
    shutil.copytree(OUT_DIR, DRIVE_OUT_FOLDER)
    print("Saved Drive zip:", DRIVE_OUT_ZIP)
    print("Saved Drive folder:", DRIVE_OUT_FOLDER)


def main() -> None:
    ensure_clean_dir(WORK_ROOT)
    ensure_clean_dir(OUT_DIR)
    OUT_WAVS.mkdir(parents=True, exist_ok=True)

    download_drive_file()
    metadata_path = extract_dataset()
    input_rows = load_metadata(metadata_path)
    print("Metadata:", metadata_path)
    print("Input rows:", len(input_rows))

    chunk_rows = []
    skipped = []
    converted_dir = WORK_ROOT / "converted"
    converted_dir.mkdir(parents=True, exist_ok=True)

    for row_index, row in enumerate(input_rows, start=1):
        try:
            src = source_wav(row, metadata_path)
            converted = converted_dir / src.name
            ffmpeg_convert(src, converted)
            duration = wav_duration(converted)
            ranges = split_ranges(duration, detect_silences(converted))
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


if __name__ == "__main__":
    main()
