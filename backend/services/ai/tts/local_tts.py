"""
Local TTS service for voice cloning inference.

Runs XTTS v2 or F5-TTS in a subprocess so the main backend process is not
blocked by model loading or GIL.  Inference scripts are written to temporary
.py files (not passed via -c) to avoid Windows quoting issues.

Output: WAV audio (24 kHz, mono, 16-bit) returned as base64.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ── Project paths ────────────────────────────────────────────────────────────
# backend/services/ai/tts/local_tts.py → 5 parents → project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
AUDIO_DIR = _PROJECT_ROOT / "audio"


# ── Cached voice discovery ───────────────────────────────────────────────────

_VOICES_CACHE: dict[str, tuple[float, list[dict]]] = {}
_VOICES_CACHE_TTL = 60.0  # seconds


def discover_voices(force: bool = False) -> list[dict]:
    """Scan the project for reference voices and fine-tuned checkpoints.

    Results are cached for ``_VOICES_CACHE_TTL`` seconds.
    """
    now = time.monotonic()
    cached = _VOICES_CACHE.get("voices")
    if cached and not force and (now - cached[0]) < _VOICES_CACHE_TTL:
        return cached[1]

    voices: list[dict] = []

    # ── Reference WAVs in audio/wavs/ ──
    _add_reference_wavs(voices)
    # ── Aswini diarized clips ──
    _add_aswini_clips(voices)
    # ── Training datasets ──
    _add_datasets(voices)
    # ── XTTS fine-tuned checkpoints ──
    _add_xtts_checkpoints(voices)

    _VOICES_CACHE["voices"] = (now, voices)
    return voices


def _add_reference_wavs(voices: list[dict]) -> None:
    wavs_dir = AUDIO_DIR / "wavs"
    if not wavs_dir.exists():
        return
    for wav in sorted(wavs_dir.glob("*.wav")):
        voices.append({
            "id": f"ref_{wav.stem}",
            "name": wav.stem,
            "speaker": wav.stem.split("_")[0] if "_" in wav.stem else "unknown",
            "language": _guess_language(wav.stem),
            "type": "reference",
            "source": "wavs",
            "reference_wav": str(wav),
            "checkpoint_path": None,
        })


def _add_aswini_clips(voices: list[dict]) -> None:
    clips_dir = AUDIO_DIR / "aswini_clips"
    if not clips_dir.exists():
        return
    wavs = sorted(clips_dir.glob("*.wav"))
    if not wavs:
        return
    voices.append({
        "id": "aswini_diarized",
        "name": f"Aswini Diarized ({len(wavs)} clips)",
        "speaker": "aswini",
        "language": "en",
        "type": "reference",
        "source": "aswini_clips",
        "reference_wav": str(wavs[0]),
        "checkpoint_path": None,
    })


def _add_datasets(voices: list[dict]) -> None:
    for ds_name in ["lk_voice_dataset_fixed", "lk_voice_dataset_chunks",
                    "lk_voice_training_final"]:
        ds_dir = AUDIO_DIR / ds_name
        if not ds_dir.exists():
            continue
        metadata_file = ds_dir / "metadata.jsonl"
        wavs_dir = ds_dir / "wavs"
        if metadata_file.exists() and wavs_dir.exists():
            wav_count = len(list(wavs_dir.glob("*.wav")))
            if wav_count > 0:
                # Try to read languages from metadata
                lang = _read_dataset_languages(metadata_file)
                voices.append({
                    "id": f"dataset_{ds_name}",
                    "name": f"Dataset: {ds_name} ({wav_count} clips, {lang})",
                    "speaker": "lk",
                    "language": lang,
                    "type": "dataset",
                    "source": ds_name,
                    "reference_wav": str(sorted(wavs_dir.glob("*.wav"))[0]) if wavs_dir.exists() else None,
                    "checkpoint_path": None,
                })


def _read_dataset_languages(jsonl_path: Path) -> str:
    """Read unique languages from first 50 rows of a metadata JSONL."""
    langs: set[str] = set()
    try:
        with jsonl_path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i >= 50:
                    break
                if line.strip():
                    row = json.loads(line)
                    lang = row.get("language", "")
                    if lang:
                        langs.add(lang)
    except Exception:
        pass
    return "+".join(sorted(langs)) if langs else "unknown"


def _add_xtts_checkpoints(voices: list[dict]) -> None:
    ft_dir = AUDIO_DIR / "xtts_finetuned"
    if not ft_dir.exists():
        return
    checkpoints = sorted(ft_dir.rglob("*.pth"))
    if not checkpoints:
        return
    voices.append({
        "id": "xtts_finetuned",
        "name": "XTTS Fine-tuned (Aswini)",
        "speaker": "aswini",
        "language": "en",
        "type": "xtts_finetuned",
        "source": "xtts_finetuned",
        "reference_wav": _find_best_reference("aswini"),
        "checkpoint_path": str(checkpoints[-1]),
    })


def _guess_language(name: str) -> str:
    """Heuristic based on filename — only used when no metadata is available."""
    lower = name.lower()
    if any(kw in lower for kw in ("hindi", "intro2", "purchase", "starting", "explain")):
        return "hi"
    if any(kw in lower for kw in ("tamil", "intro1", "paragraph1", "business", "emotion")):
        return "ta"
    if any(kw in lower for kw in ("bhojpuri", "intro3", "gags")):
        return "bho"
    if "mixed" in lower:
        return "mixed"
    return "en"


def _find_best_reference(speaker: str) -> str | None:
    wavs_dir = AUDIO_DIR / "wavs"
    if not wavs_dir.exists():
        return None
    candidates = sorted(wavs_dir.glob(f"*{speaker}*.wav"))
    if candidates:
        return str(candidates[0])
    all_wavs = sorted(wavs_dir.glob("*.wav"))
    return str(all_wavs[0]) if all_wavs else None


# ── Python 3.10 (XTTS) resolver ──────────────────────────────────────────────

def get_xtts_python() -> str | None:
    """Return a Python 3.10 interpreter for XTTS v2, or None."""
    candidates = [
        AUDIO_DIR / "tts_env" / "Scripts" / "python.exe",
        AUDIO_DIR / "tts_env" / "bin" / "python",
    ]
    for p in candidates:
        if p.exists():
            return str(p)
    try:
        out = subprocess.run(
            ["python", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if "3.10" in out.stdout:
            return "python"
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["python3.10", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if "3.10" in out.stdout:
            return "python3.10"
    except Exception:
        pass
    return None


# ── Inference script templates ───────────────────────────────────────────────
# These are written to temp .py files to avoid Windows -c quoting issues.

XTTS_INFERENCE_SRC = r'''"""Auto-generated by local_tts.py — XTTS v2 inference."""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"

def main() -> None:
    args = json.loads(sys.argv[1])
    text = args["text"]
    speaker_wav = args.get("speaker_wav", "")
    language = args.get("language", "en")
    checkpoint_path = args.get("checkpoint_path")
    output_path = args["output_path"]

    # Decode inline base64 WAV
    if speaker_wav.startswith("__b64__"):
        b64_data = speaker_wav.replace("__b64__", "")
        tmp = Path(output_path).parent / "_tmp_ref.wav"
        tmp.write_bytes(base64.b64decode(b64_data))
        speaker_wav = str(tmp)

    from TTS.api import TTS

    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)

    if checkpoint_path and Path(checkpoint_path).exists():
        import torch
        state = torch.load(checkpoint_path, map_location="cpu")
        if "model" in state:
            tts.synthesizer.tts_model.load_state_dict(state["model"], strict=False)

    tts.tts_to_file(text=text, speaker_wav=speaker_wav, language=language, file_path=output_path)

    with open(output_path, "rb") as f:
        wav_bytes = f.read()

    result = {
        "success": True,
        "audio_base64": base64.b64encode(wav_bytes).decode("utf-8"),
        "sample_rate": 24000,
        "duration": round(len(wav_bytes) / 48000, 2),
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()
'''

F5_INFERENCE_SRC = r'''"""Auto-generated by local_tts.py — F5-TTS inference."""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import soundfile as sf
import torch
import torchaudio

def _sf_load(path, *args, **kwargs):
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr

torchaudio.load = _sf_load

def main() -> None:
    args = json.loads(sys.argv[1])
    text = args["text"]
    ref_audio = args["ref_audio"]
    ref_text = args.get("ref_text", "")
    output_path = args["output_path"]

    from f5_tts.api import F5TTS

    tts = F5TTS()
    tts.infer(
        ref_file=ref_audio,
        ref_text=ref_text[:1200],
        gen_text=text,
        file_wave=output_path,
        show_info=print,
    )

    with open(output_path, "rb") as f:
        wav_bytes = f.read()

    result = {
        "success": True,
        "audio_base64": base64.b64encode(wav_bytes).decode("utf-8"),
        "sample_rate": 24000,
        "duration": round(len(wav_bytes) / 48000, 2),
    }
    print(json.dumps(result))

if __name__ == "__main__":
    main()
'''


def _write_inference_script(src: str) -> Path:
    """Write an inference script to a temp file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".py", prefix="tts_infer_", text=True)
    os.write(fd, src.encode("utf-8"))
    os.close(fd)
    return Path(path)


# ── XTTS v2 inference ────────────────────────────────────────────────────────

async def run_xtts_inference(
    text: str,
    speaker_wav: str | None = None,
    language: str = "en",
    checkpoint_path: str | None = None,
    timeout: int = 120,
) -> dict:
    """Run XTTS v2 inference via subprocess (requires Python 3.10).

    Returns dict with keys: success, audio_base64, sample_rate, duration, error.
    """
    python_exe = get_xtts_python()
    if not python_exe:
        return {
            "success": False,
            "error": (
                "XTTS v2 requires Python 3.10. "
                "Set up the environment: cd audio && python -m venv tts_env && "
                "tts_env\\Scripts\\pip install TTS soundfile"
            ),
        }

    if not speaker_wav:
        wavs_dir = AUDIO_DIR / "wavs"
        wavs = sorted(wavs_dir.glob("*.wav"))
        if not wavs:
            return {"success": False, "error": "No reference WAV available for voice cloning."}
        speaker_wav = str(wavs[0])

    script_path = _write_inference_script(XTTS_INFERENCE_SRC)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        output_path = tmp.name

    payload = {
        "text": text,
        "speaker_wav": speaker_wav,
        "language": language,
        "checkpoint_path": checkpoint_path,
        "output_path": output_path,
    }

    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe, str(script_path), json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(AUDIO_DIR),
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            return {
                "success": False,
                "error": f"XTTS subprocess exited with code {proc.returncode}: {stderr.decode()[:500]}",
            }

        # Last JSON line from stdout is the result
        for line in reversed(stdout.decode().strip().split("\n")):
            try:
                result = json.loads(line)
                if isinstance(result, dict) and result.get("success"):
                    return result
            except json.JSONDecodeError:
                continue

        return {
            "success": False,
            "error": f"No valid result in XTTS output: {stdout.decode()[:300]}",
        }

    except asyncio.TimeoutError:
        return {"success": False, "error": f"XTTS inference timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ── F5-TTS inference ─────────────────────────────────────────────────────────

async def run_f5_inference(
    text: str,
    ref_audio: str,
    ref_text: str = "",
    timeout: int = 180,
) -> dict:
    """Run F5-TTS zero-shot inference via subprocess (uses backend Python)."""
    script_path = _write_inference_script(F5_INFERENCE_SRC)

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        output_path = tmp.name

    payload = {
        "text": text,
        "ref_audio": ref_audio,
        "ref_text": ref_text,
        "output_path": output_path,
    }

    python_exe = sys.executable  # F5-TTS works with Python 3.11+

    try:
        proc = await asyncio.create_subprocess_exec(
            python_exe, str(script_path), json.dumps(payload),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(AUDIO_DIR),
        )

        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)

        if proc.returncode != 0:
            return {
                "success": False,
                "error": f"F5 subprocess exited with code {proc.returncode}: {stderr.decode()[:500]}",
            }

        for line in reversed(stdout.decode().strip().split("\n")):
            try:
                result = json.loads(line)
                if isinstance(result, dict) and result.get("success"):
                    return result
            except json.JSONDecodeError:
                continue

        return {
            "success": False,
            "error": f"No valid result in F5 output: {stdout.decode()[:300]}",
        }

    except asyncio.TimeoutError:
        return {"success": False, "error": f"F5-TTS inference timed out after {timeout}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        try:
            os.unlink(output_path)
        except OSError:
            pass
        try:
            os.unlink(script_path)
        except OSError:
            pass


# ── High-level synthesis ─────────────────────────────────────────────────────

async def synthesize(
    text: str,
    voice_id: str = "xtts_finetuned",
    language: str = "en",
    engine: str = "xtts",
) -> dict:
    """Synthesize speech using the selected voice.

    Routes to the correct engine based on voice_id / engine param.
    Returns dict with keys: success, audio_base64, sample_rate, duration, error.
    """
    text = text.strip()
    if not text:
        return {"success": False, "error": "Empty text"}

    voices = {v["id"]: v for v in discover_voices()}
    voice = voices.get(voice_id)

    if engine == "f5" or (voice and voice["type"] == "reference"):
        # F5-TTS zero-shot (works on any reference WAV)
        ref_wav = voice["reference_wav"] if voice else None
        if not ref_wav:
            return {"success": False, "error": f"Voice '{voice_id}' not found or has no reference WAV"}
        return await run_f5_inference(text=text, ref_audio=ref_wav)

    # XTTS v2 (default)
    speaker_wav = voice.get("reference_wav") if voice else None
    checkpoint_path = voice.get("checkpoint_path") if voice else None

    return await run_xtts_inference(
        text=text,
        speaker_wav=speaker_wav,
        language=language,
        checkpoint_path=checkpoint_path,
    )
