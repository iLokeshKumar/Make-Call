"""
Sync derived metadata files from metadata_pipe.csv.

Source of truth, read-only:
  audio/lk_voice_dataset_chunks/metadata_pipe.csv

Rewritten files:
  audio/lk_voice_dataset_chunks/metadata.csv
  audio/lk_voice_dataset_chunks/review.csv
  audio/lk_voice_dataset_chunks/metadata.jsonl

Before writing, creates:
  audio/lk_voice_dataset_chunks/backups/sync_YYYYMMDD_HHMMSS/
"""

from __future__ import annotations

import csv
import json
import shutil
from datetime import datetime
from pathlib import Path


DATASET_DIR = Path(__file__).resolve().parent / "lk_voice_dataset_chunks"
PIPE_PATH = DATASET_DIR / "metadata_pipe.csv"
METADATA_CSV = DATASET_DIR / "metadata.csv"
REVIEW_CSV = DATASET_DIR / "review.csv"
METADATA_JSONL = DATASET_DIR / "metadata.jsonl"

DERIVED_FILES = [METADATA_CSV, REVIEW_CSV, METADATA_JSONL]


def clip_id_from_audio_file(value: str) -> str:
    return Path((value or "").replace("\\", "/")).stem


def read_pipe(path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}
    duplicates: list[str] = []

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\n\r")
            if not line.strip():
                continue
            if "|" not in line:
                raise ValueError(f"{path} line {line_number} has no pipe delimiter")
            clip_id, text = line.split("|", 1)
            clip_id = clip_id.strip()
            text = " ".join(text.strip().split())
            if not clip_id:
                raise ValueError(f"{path} line {line_number} has empty clip id")
            if clip_id in mapping:
                duplicates.append(clip_id)
            mapping[clip_id] = text

    if duplicates:
        raise ValueError(f"Duplicate clip ids in metadata_pipe.csv: {duplicates[:10]}")
    return mapping


def backup_files() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = DATASET_DIR / "backups" / f"sync_{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    for path in DERIVED_FILES:
        if path.exists():
            shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def sync_csv(path: Path, pipe_text: dict[str, str]) -> tuple[int, list[str], list[str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError(f"{path} has no header")
        fieldnames = list(reader.fieldnames)
        rows = list(reader)

    if "audio_file" not in fieldnames:
        raise ValueError(f"{path} missing audio_file column")
    if "text" not in fieldnames:
        raise ValueError(f"{path} missing text column")

    updated = 0
    missing_in_pipe: list[str] = []
    seen: set[str] = set()

    for row in rows:
        clip_id = clip_id_from_audio_file(row.get("audio_file", ""))
        seen.add(clip_id)
        if clip_id not in pipe_text:
            missing_in_pipe.append(clip_id)
            continue
        row["text"] = pipe_text[clip_id]
        updated += 1

    extra_in_pipe = sorted(set(pipe_text) - seen)

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return updated, missing_in_pipe, extra_in_pipe


def sync_jsonl(path: Path, pipe_text: dict[str, str]) -> tuple[int, list[str], list[str]]:
    rows = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))

    updated = 0
    missing_in_pipe: list[str] = []
    seen: set[str] = set()

    for row in rows:
        clip_id = clip_id_from_audio_file(row.get("audio_file", ""))
        seen.add(clip_id)
        if clip_id not in pipe_text:
            missing_in_pipe.append(clip_id)
            continue
        row["text"] = pipe_text[clip_id]
        updated += 1

    extra_in_pipe = sorted(set(pipe_text) - seen)

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    return updated, missing_in_pipe, extra_in_pipe


def main() -> None:
    if not PIPE_PATH.exists():
        raise FileNotFoundError(f"Missing source of truth: {PIPE_PATH}")
    for path in DERIVED_FILES:
        if not path.exists():
            raise FileNotFoundError(f"Missing derived file: {path}")

    pipe_text = read_pipe(PIPE_PATH)
    backup_dir = backup_files()

    report = {
        "source": str(PIPE_PATH),
        "source_rows": len(pipe_text),
        "backup_dir": str(backup_dir),
        "files": {},
    }

    for path in [METADATA_CSV, REVIEW_CSV]:
        updated, missing, extra = sync_csv(path, pipe_text)
        report["files"][path.name] = {
            "updated": updated,
            "missing_in_pipe": missing,
            "extra_in_pipe": extra,
        }

    updated, missing, extra = sync_jsonl(METADATA_JSONL, pipe_text)
    report["files"][METADATA_JSONL.name] = {
        "updated": updated,
        "missing_in_pipe": missing,
        "extra_in_pipe": extra,
    }

    report_path = backup_dir / "sync_report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Source rows: {len(pipe_text)}")
    print(f"Backup: {backup_dir}")
    for filename, details in report["files"].items():
        print(
            f"{filename}: updated={details['updated']} "
            f"missing_in_pipe={len(details['missing_in_pipe'])} "
            f"extra_in_pipe={len(details['extra_in_pipe'])}"
        )
    print(f"Report: {report_path}")


if __name__ == "__main__":
    main()
