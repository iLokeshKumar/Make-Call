"""
XTTS v2 zero-shot voice test.

Local:
  audio/tts_env/Scripts/python.exe audio/colab_B_xtts_py310.py

Colab:
  1. Open a fresh Colab notebook.
  2. Runtime -> Change runtime type -> T4 GPU.
  3. Upload this file or paste it into one cell:
       %run /content/colab_B_xtts_py310.py -- --colab
  4. If Colab restarts after condacolab install, run the same file again.

Input expected in Google Drive:
  MyDrive/rio_voice/final/lk_voice_training_final.zip

Output:
  MyDrive/rio_voice/experiments/xtts_zero_shot/

This file does NOT import Coqui TTS in the notebook kernel. It creates a Python
3.10 conda env and runs XTTS inside that env.
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


ENV_NAME = "xtts310"
INNER_SCRIPT = Path("/content/run_xtts_zero_shot_inner.py")


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, check=check)


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
    parser = argparse.ArgumentParser(description="Run XTTS v2 zero-shot samples.")
    parser.add_argument("--colab", action="store_true", help="Use Google Drive paths and Colab conda setup.")
    parser.add_argument("--dataset", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=Path(os.environ["XTTS_OUTPUT"]) if "XTTS_OUTPUT" in os.environ else None)
    parser.add_argument("--work-dir", type=Path, default=Path(os.environ.get("XTTS_WORK_DIR", Path(__file__).resolve().parent / ".work" / "xtts_lk_work")))
    parser.add_argument("--max-ref-seconds", type=float, default=45.0)
    parser.add_argument("--gpu", choices=["auto", "true", "false"], default=os.environ.get("XTTS_GPU", "auto"))
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


def use_gpu(setting: str) -> bool:
    if setting == "true":
        return True
    if setting == "false":
        return False
    import torch
    return bool(torch.cuda.is_available())


def conda_exists() -> bool:
    return shutil.which("conda") is not None


def conda_env_exists() -> bool:
    result = subprocess.run(["conda", "env", "list"], text=True, capture_output=True)
    return ENV_NAME in result.stdout


def ensure_conda() -> None:
    if conda_exists():
        print("Conda already available.")
        return
    print("Installing condacolab. Colab will restart. After restart, run this same file again.")
    run([sys.executable, "-m", "pip", "install", "-q", "condacolab"])
    import condacolab
    condacolab.install()


def ensure_env() -> None:
    if not conda_exists():
        raise RuntimeError("Conda is not available yet. Run this file again after Colab restart.")

    if conda_env_exists():
        print(f"Conda env {ENV_NAME} already exists.")
        return

    run(["conda", "create", "-n", ENV_NAME, "python=3.10", "-y"])
    run(["conda", "run", "-n", ENV_NAME, "python", "-m", "pip", "install", "-q", "--upgrade", "pip"])
    run([
        "conda", "run", "-n", ENV_NAME, "python", "-m", "pip", "install", "-q",
        "TTS==0.22.0", "soundfile",
    ])


def write_inner_script() -> None:
    INNER_SCRIPT.write_text(
        r'''
from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def main() -> None:
    from TTS.api import TTS

    drive_base = Path("/content/drive/MyDrive/rio_voice")
    final_zip = drive_base / "final" / "lk_voice_training_final.zip"
    work_dir = Path("/content/xtts_lk_work")
    dataset_dir = work_dir / "lk_voice_training_final"
    ref_dir = Path("/content/xtts_refs")
    out_dir = drive_base / "experiments" / "xtts_zero_shot"

    if not final_zip.exists():
        raise FileNotFoundError(f"Missing final dataset zip: {final_zip}")

    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Extracting dataset...")
    with zipfile.ZipFile(final_zip, "r") as archive:
        archive.extractall(work_dir)

    if not dataset_dir.exists():
        dirs = [p for p in work_dir.iterdir() if p.is_dir()]
        if not dirs:
            raise RuntimeError("No dataset folder found after unzip")
        dataset_dir = dirs[0]

    rows = []
    with (dataset_dir / "metadata.jsonl").open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))

    print("Dataset:", dataset_dir)
    print("Rows:", len(rows))
    print("Wavs:", len(list((dataset_dir / "wavs").glob("*.wav"))))

    def rows_for_language(language: str, max_total_seconds: float = 45.0) -> list[dict]:
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

    def make_reference(language: str) -> Path:
        selected = rows_for_language(language)
        if not selected:
            raise RuntimeError(f"No reference clips found for language={language}")

        list_path = Path("/content") / f"xtts_concat_{language}.txt"
        with list_path.open("w", encoding="utf-8") as handle:
            for row in selected:
                handle.write(f"file '{dataset_dir / row['audio_file']}'\n")

        ref_wav = ref_dir / f"lk_ref_{language}.wav"
        run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-ac", "1", "-ar", "24000", str(ref_wav),
        ])
        return ref_wav

    test_texts = {
        "english": ("en", "Hello, this is Lokesh calling from Yexis Electronics. I wanted to understand your display requirement."),
        "hindi": ("hi", "Namaste sir, main Yexis Electronics se Lokesh bol raha hoon. Aapki display requirement samajhna chahta hoon."),
        "tamil": ("ta", "Vanakkam sir, naan Yexis Electronics la irundhu Lokesh pesuren. Ungal display requirement purinjukkanum."),
        "bhojpuri": ("hi", "Namaste sir, hum Yexis Electronics se Lokesh bolat bani. Raur display requirement samjhe ke ba."),
    }

    print("Loading XTTS v2...")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)

    for language, (lang_code, text) in test_texts.items():
        try:
            ref_wav = make_reference(language)
            out_wav = out_dir / f"xtts_{language}.wav"
            print(f"\nXTTS {language}: {out_wav}")
            tts.tts_to_file(
                text=text,
                speaker_wav=str(ref_wav),
                language=lang_code,
                file_path=str(out_wav),
            )
        except Exception as exc:
            print(f"FAILED {language}: {exc}")

    print("\nDONE")
    print("XTTS outputs saved to:", out_dir)


if __name__ == "__main__":
    main()
''',
        encoding="utf-8",
    )
    print("Wrote:", INNER_SCRIPT)


def run_local(args: argparse.Namespace) -> None:
    os.environ["COQUI_TOS_AGREED"] = "1"
    from TTS.api import TTS

    out_dir = args.output or Path(__file__).resolve().parent / "experiments" / "xtts_zero_shot"
    ref_dir = args.work_dir.parent / "xtts_refs"
    out_dir.mkdir(parents=True, exist_ok=True)
    ref_dir.mkdir(parents=True, exist_ok=True)

    dataset_dir = prepare_dataset(args.dataset or dataset_for_mode(False), args.work_dir)
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

    def make_reference(language: str) -> Path:
        selected = rows_for_language(language)
        if not selected:
            raise RuntimeError(f"No reference clips found for language={language}")
        ref_wav = ref_dir / f"lk_ref_{language}.wav"
        concat_reference_wavs(selected, dataset_dir, ref_wav)
        return ref_wav

    test_texts = {
        "english": ("en", "Hello, this is Lokesh calling from Yexis Electronics. I wanted to understand your display requirement."),
        "hindi": ("hi", "Namaste sir, main Yexis Electronics se Lokesh bol raha hoon. Aapki display requirement samajhna chahta hoon."),
        "tamil": ("ta", "Vanakkam sir, naan Yexis Electronics la irundhu Lokesh pesuren. Ungal display requirement purinjukkanum."),
        "bhojpuri": ("hi", "Namaste sir, hum Yexis Electronics se Lokesh bolat bani. Raur display requirement samjhe ke ba."),
    }

    gpu = use_gpu(args.gpu)
    print(f"Loading XTTS v2... gpu={gpu}")
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=gpu)
    print("XTTS v2 loaded. Starting generation...", flush=True)

    for language, (lang_code, text) in test_texts.items():
        try:
            ref_wav = make_reference(language)
            out_wav = out_dir / f"xtts_{language}.wav"
            print(f"\nXTTS {language}: {out_wav}", flush=True)
            tts.tts_to_file(
                text=text,
                speaker_wav=str(ref_wav),
                language=lang_code,
                file_path=str(out_wav),
            )
        except Exception as exc:
            print(f"FAILED {language}: {exc}")

    print("\nDONE")
    print("XTTS outputs saved to:", out_dir)


def run_colab() -> None:
    from google.colab import drive

    drive.mount("/content/drive")
    ensure_conda()
    ensure_env()
    write_inner_script()
    run(["conda", "run", "-n", ENV_NAME, "python", str(INNER_SCRIPT)])
    print("DONE. XTTS outputs are in MyDrive/rio_voice/experiments/xtts_zero_shot/")


def main() -> None:
    args = parse_args()
    if args.colab:
        if not in_colab():
            raise RuntimeError("--colab was passed, but this does not look like a Colab runtime")
        run_colab()
    else:
        run_local(args)


if __name__ == "__main__":
    main()
