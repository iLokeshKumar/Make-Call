"""
Google Colab script: build final LK training dataset from reviewed chunks.

Input in Drive:
  /content/drive/MyDrive/rio_voice/output/lk_voice_dataset_chunks/
    wavs/
    review.csv

Output in Drive:
  /content/drive/MyDrive/rio_voice/final/lk_voice_training_final.zip
  /content/drive/MyDrive/rio_voice/final/lk_voice_training_final/

Review policy:
  - Rows are kept unless `keep` is explicitly a reject value:
    no, n, false, 0, reject, rejected, remove, delete, bad
  - If you used `keep=yes/no`, only non-rejected rows remain.
  - Corrected `text` values in review.csv are used.
"""

from __future__ import annotations

import csv
import json
import shutil
import zipfile
from collections import Counter
from pathlib import Path


DRIVE_BASE = Path("/content/drive/MyDrive/rio_voice")
REVIEWED_DIR = DRIVE_BASE / "output" / "lk_voice_dataset_chunks"
REVIEW_CSV = REVIEWED_DIR / "review.csv"
SOURCE_WAVS = REVIEWED_DIR / "wavs"

FINAL_DIR = DRIVE_BASE / "final" / "lk_voice_training_final"
FINAL_WAVS = FINAL_DIR / "wavs"
FINAL_ZIP = DRIVE_BASE / "final" / "lk_voice_training_final.zip"

REJECT_VALUES = {"no", "n", "false", "0", "reject", "rejected", "remove", "delete", "bad"}


def normalize_text(value: str) -> str:
    return " ".join((value or "").split())


def should_keep(row: dict) -> bool:
    keep_value = normalize_text(row.get("keep", "")).lower()
    if keep_value in REJECT_VALUES:
        return False
    if not normalize_text(row.get("text", "")):
        return False
    return True


def clean_output() -> None:
    if FINAL_DIR.exists():
        shutil.rmtree(FINAL_DIR)
    FINAL_WAVS.mkdir(parents=True, exist_ok=True)
    FINAL_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if FINAL_ZIP.exists():
        FINAL_ZIP.unlink()


def main() -> None:
    if not REVIEW_CSV.exists():
        raise FileNotFoundError(f"Missing review file: {REVIEW_CSV}")
    if not SOURCE_WAVS.exists():
        raise FileNotFoundError(f"Missing wav folder: {SOURCE_WAVS}")

    clean_output()

    with REVIEW_CSV.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    kept = []
    rejected = []
    missing_audio = []

    for row in rows:
        if not should_keep(row):
            rejected.append(row)
            continue

        source_rel = row.get("audio_file", "")
        source_wav = REVIEWED_DIR / source_rel
        if not source_wav.exists():
            source_wav = SOURCE_WAVS / Path(source_rel).name
        if not source_wav.exists():
            missing_audio.append(source_rel)
            continue

        #out_name = f"lk_{len(kept) + 1:04d}_{Path(source_wav).name}"
        out_name = Path(source_wav).name
        out_wav = FINAL_WAVS / out_name
        shutil.copy2(source_wav, out_wav)

        item = {
            "audio_file": f"wavs/{out_name}",
            "speaker": row.get("speaker", "lk") or "lk",
            "language": row.get("language", ""),
            "duration": float(row.get("duration") or 0),
            "text": normalize_text(row.get("text", "")),
            "source_audio_file": row.get("source_audio_file", ""),
            "source_start": row.get("source_start", ""),
            "source_end": row.get("source_end", ""),
            "notes": row.get("notes", ""),
        }
        kept.append(item)

    metadata_fields = [
        "audio_file",
        "speaker",
        "language",
        "duration",
        "text",
        "source_audio_file",
        "source_start",
        "source_end",
        "notes",
    ]

    with (FINAL_DIR / "metadata.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=metadata_fields)
        writer.writeheader()
        writer.writerows(kept)

    with (FINAL_DIR / "metadata.jsonl").open("w", encoding="utf-8") as handle:
        for item in kept:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    with (FINAL_DIR / "metadata_pipe.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="|")
        for item in kept:
            writer.writerow([Path(item["audio_file"]).stem, item["text"]])

    # Simple deterministic split for training scripts that expect train/val metadata.
    train_count = int(len(kept) * 0.9)
    train_rows = kept[:train_count]
    val_rows = kept[train_count:]
    for filename, split_rows in [("metadata_train.jsonl", train_rows), ("metadata_val.jsonl", val_rows)]:
        with (FINAL_DIR / filename).open("w", encoding="utf-8") as handle:
            for item in split_rows:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    by_language = Counter(item["language"] for item in kept)
    total_minutes = sum(item["duration"] for item in kept) / 60.0
    readme = [
        "LK final reviewed training dataset",
        "",
        f"Source: {REVIEW_CSV}",
        f"Kept clips: {len(kept)}",
        f"Rejected/empty clips: {len(rejected)}",
        f"Missing audio rows: {len(missing_audio)}",
        f"Total minutes: {total_minutes:.2f}",
        "",
        "By language:",
    ]
    for language, count in sorted(by_language.items()):
        minutes = sum(item["duration"] for item in kept if item["language"] == language) / 60.0
        readme.append(f"- {language}: {count} clips, {minutes:.2f} min")
    if missing_audio:
        readme.extend(["", "Missing audio:"])
        readme.extend(f"- {path}" for path in missing_audio[:50])
    (FINAL_DIR / "README.txt").write_text("\n".join(readme) + "\n", encoding="utf-8")

    with zipfile.ZipFile(FINAL_ZIP, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(FINAL_DIR.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(FINAL_DIR.parent))

    print("Kept clips:", len(kept))
    print("Rejected/empty clips:", len(rejected))
    print("Missing audio rows:", len(missing_audio))
    print("Total minutes:", round(total_minutes, 2))
    print("Final folder:", FINAL_DIR)
    print("Final zip:", FINAL_ZIP)


if __name__ == "__main__":
    main()
