"""
F5-TTS zero-shot voice test.

Local:
  backend/myenvironment/Scripts/python.exe audio/colab_A_f5_tts.py

Colab:
  1. Open a fresh Colab notebook.
  2. Runtime -> Change runtime type -> T4 GPU.
  3. Upload this file or paste it into one cell:
       %run /content/colab_A_f5_tts.py -- --colab

Colab input expected in Google Drive:
  MyDrive/rio_voice/final/lk_voice_training_final.zip

Colab output:
  MyDrive/rio_voice/experiments/f5_zero_shot/
"""

from __future__ import annotations

import argparse
import faulthandler
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

faulthandler.enable()


def pip_install(*packages: str) -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", *packages], check=True)


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def in_colab() -> bool:
    return "google.colab" in sys.modules or Path("/content").exists()


def local_dataset() -> Path:
    local_dataset = Path(__file__).resolve().parent / "lk_voice_dataset_chunks"
    return local_dataset


def dataset_for_mode(colab: bool) -> Path:
    if "LK_TTS_DATASET" in os.environ:
        return Path(os.environ["LK_TTS_DATASET"])
    if colab:
        return Path("/content/drive/MyDrive/rio_voice/final/lk_voice_training_final.zip")
    return local_dataset()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run F5-TTS zero-shot samples.")
    parser.add_argument("--colab", action="store_true", help="Use Google Drive paths and Colab setup.")
    parser.add_argument("--install-deps", action="store_true", help="Install Python deps before running.")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path(os.environ["F5_TTS_OUTPUT"]) if "F5_TTS_OUTPUT" in os.environ else None)
    parser.add_argument("--work-dir", type=Path, default=Path(os.environ.get("F5_TTS_WORK_DIR", Path(__file__).resolve().parent / ".work" / "f5_lk_work")))
    parser.add_argument("--max-ref-seconds", type=float, default=45.0)
    return parser.parse_args()


def prepare_dataset(dataset: Path, work_dir: Path) -> Path:
    dataset = dataset.resolve()
    if dataset.is_dir():
        return dataset
    if not dataset.exists():
        raise FileNotFoundError(f"Missing dataset: {dataset}")

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    print("Extracting dataset...")
    with zipfile.ZipFile(dataset, "r") as archive:
        archive.extractall(work_dir)

    expected = work_dir / "lk_voice_training_final"
    if expected.exists():
        return expected
    dirs = [p for p in work_dir.iterdir() if p.is_dir()]
    if not dirs:
        raise RuntimeError("No dataset folder found after unzip")
    return dirs[0]


def concat_reference_wavs(rows: list[dict], dataset_dir: Path, out_wav: Path) -> None:
    import numpy as np
    import soundfile as sf

    audio_parts = []
    sample_rate = None
    for row in rows:
        wav_path = dataset_dir / row["audio_file"]
        data, sr = sf.read(str(wav_path), dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1)
        if sample_rate is None:
            sample_rate = sr
        elif sr != sample_rate:
            raise RuntimeError(f"Sample rate mismatch in {wav_path}: {sr} != {sample_rate}")
        audio_parts.append(data)

    if not audio_parts or sample_rate is None:
        raise RuntimeError("No audio available for reference WAV")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_wav), np.concatenate(audio_parts), sample_rate)


def main() -> None:
    args = parse_args()

    if args.colab:
        if not in_colab():
            raise RuntimeError("--colab was passed, but this does not look like a Colab runtime")
        from google.colab import drive
        drive.mount("/content/drive")

    if args.install_deps:
        print("Installing F5-TTS dependencies...")
        pip_install("--upgrade", "pip")
        pip_install("soundfile", "git+https://github.com/SWivid/F5-TTS.git")

    import soundfile as sf
    import torch
    import torchaudio
    from f5_tts.api import F5TTS
    try:
        from IPython.display import Audio, display
    except Exception:
        Audio = None
        display = None

    # F5 sometimes uses torchaudio.load. This shim avoids backend issues.
    def _sf_load(path, *args, **kwargs):
        data, sr = sf.read(str(path), dtype="float32", always_2d=True)
        return torch.from_numpy(data.T), sr

    torchaudio.load = _sf_load

    if args.output is not None:
        out_dir = args.output
    elif args.colab:
        out_dir = Path("/content/drive/MyDrive/rio_voice/experiments/f5_zero_shot")
    else:
        out_dir = Path(__file__).resolve().parent / "experiments" / "f5_zero_shot"
    ref_dir = args.work_dir.parent / "f5_refs"
    ref_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    dataset_dir = prepare_dataset(args.dataset or dataset_for_mode(args.colab), args.work_dir)

    rows = []
    with (dataset_dir / "metadata.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))

    print("Dataset:", dataset_dir)
    print("Rows:", len(rows))
    print("Wavs:", len(list((dataset_dir / "wavs").glob("*.wav"))))

    def rows_for_language(language: str, max_total_seconds: float = args.max_ref_seconds) -> list[dict]:
        selected = []
        total = 0.0
        for row in rows:
            if row.get("language") != language:
                continue
            duration = float(row.get("duration") or 0)
            if duration < 3 or duration > 18:
                continue
            selected.append(row)
            total += duration
            if total >= max_total_seconds:
                break
        return selected

    def make_reference(language: str) -> tuple[Path, str]:
        selected = rows_for_language(language)
        if not selected:
            raise RuntimeError(f"No reference clips found for language={language}")

        ref_wav = ref_dir / f"lk_ref_{language}.wav"
        concat_reference_wavs(selected, dataset_dir, ref_wav)
        ref_text = " ".join(row["text"] for row in selected)
        return ref_wav, ref_text

    test_texts = {
        "english": "Hello, this is Lokesh calling from Yexis Electronics. I wanted to understand your display requirement.",
        "hindi": "Namaste sir, main Yexis Electronics se Lokesh bol raha hoon. Aapki display requirement samajhna chahta hoon.",
        "tamil": "Vanakkam sir, naan Yexis Electronics la irundhu Lokesh pesuren. Ungal display requirement purinjukkanum.",
        "bhojpuri": "Namaste sir, hum Yexis Electronics se Lokesh bolat bani. Raur display requirement samjhe ke ba.",
    }

    print("Loading F5-TTS...")
    f5 = F5TTS()
    print("F5-TTS loaded. Starting generation...", flush=True)

    for language, gen_text in test_texts.items():
        try:
            ref_wav, ref_text = make_reference(language)
            out_wav = out_dir / f"f5_{language}.wav"
            print(f"\nF5 {language}: {out_wav}", flush=True)
            f5.infer(
                ref_file=str(ref_wav),
                ref_text=ref_text[:1200],
                gen_text=gen_text,
                file_wave=str(out_wav),
                show_info=print,
            )
            if Audio is not None and display is not None:
                display(Audio(str(out_wav)))
        except Exception as exc:
            print(f"FAILED {language}: {exc}")

    print("\nDONE")
    print("F5 outputs saved to:", out_dir)


if __name__ == "__main__":
    main()
