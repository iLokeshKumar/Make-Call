"""
F5-TTS Demo — SHORT reference version.

Extracts a ~10 second clip from the clean recording and uses it
as reference for F5-TTS. Shorter reference = faster CPU inference.

Usage:
    backend/myenvironment/Scripts/python.exe audio/f5_demo_short.py

Output:
    audio/f5_demo_short_output/*.wav
"""

from __future__ import annotations

import json
import os
import sys
import time
import wave
from pathlib import Path

import soundfile as sf
import torch
import torchaudio

# ---- F5-TTS shim ----
def _sf_load(path, *a, **kw):
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr

torchaudio.load = _sf_load

from f5_tts.api import F5TTS

ROOT = Path(__file__).resolve().parent
NORMALIZED = ROOT / "my_voice_recordings" / "normalized"
OUT_DIR = ROOT / "f5_demo_short_output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Step 1: Extract a short clip from the intro recording ----
# The intro recording "lk_intro.wav" contains:
# "Hello, good morning. I hope you are doing well today. My name is Ashwini..."
# We extract the first ~12 seconds.

SOURCE_WAV = NORMALIZED / "lk_intro.wav"
REF_CLIP = OUT_DIR / "ref_clip.wav"
CLIP_TEXT = "Hello, good morning. I hope you are doing well today. My name is Ashwini, and I am calling from Yexis Electronics."
CLIP_DURATION_SEC = 12.0  # extract first 12 seconds

print("Extracting short reference clip...")
with wave.open(str(SOURCE_WAV), "rb") as src:
    sr = src.getframerate()
    n_channels = src.getnchannels()
    sampwidth = src.getsampwidth()
    n_frames = int(sr * CLIP_DURATION_SEC)
    frames = src.readframes(n_frames)

with wave.open(str(REF_CLIP), "wb") as dst:
    dst.setnchannels(n_channels)
    dst.setsampwidth(sampwidth)
    dst.setframerate(sr)
    dst.writeframes(frames)

duration = len(frames) / sampwidth / sr
print(f"  Clip duration: {duration:.1f}s")
print(f"  Clip text: '{CLIP_TEXT[:60]}...'")

# ---- Step 2: Sentences to generate ----
DEMO_SENTENCES = [
    "Hello, good morning. This is Ashwini calling from Yexis Electronics.",
    "I just wanted to understand whether you have any requirement for displays or signage boards.",
    "Thank you for your time. I really appreciate it. Have a good day.",
]

# ---- Step 3: Load F5-TTS and generate ----
print("\nLoading F5-TTS...")
start = time.time()
tts = F5TTS()
print(f"Loaded in {time.time() - start:.1f}s\n")

results = []

for i, gen_text in enumerate(DEMO_SENTENCES):
    out_name = f"demo_{i:02d}.wav"
    out_path = OUT_DIR / out_name

    if out_path.exists():
        size_kb = out_path.stat().st_size / 1024
        print(f"[{i+1}/{len(DEMO_SENTENCES)}] {out_name} exists ({size_kb:.0f}KB), skipping")
        results.append({"sentence": gen_text, "output": str(out_path), "status": "cached", "size_kb": size_kb})
        continue

    print(f"[{i+1}/{len(DEMO_SENTENCES)}] Generating: '{gen_text}'")
    print(f"  This may take 2-5 minutes on CPU...", flush=True)
    gen_start = time.time()
    try:
        tts.infer(
            ref_file=str(REF_CLIP),
            ref_text=CLIP_TEXT,
            gen_text=gen_text,
            file_wave=str(out_path),
            show_info=print,
        )
        elapsed = time.time() - gen_start
        size_kb = out_path.stat().st_size / 1024
        print(f"  Done in {elapsed:.1f}s, {size_kb:.0f}KB\n")
        results.append({"sentence": gen_text, "output": str(out_path), "status": "generated", "time_sec": round(elapsed, 1), "size_kb": round(size_kb, 0)})
    except Exception as e:
        print(f"  FAILED: {e}\n")
        results.append({"sentence": gen_text, "output": "", "status": "error", "error": str(e)})

# ---- Summary ----
print("=" * 50)
print("RESULTS")
print("=" * 50)
for r in results:
    if r["status"] in ("generated", "cached"):
        print(f"  OK: {Path(r['output']).name}")
    elif r["status"] == "error":
        print(f"  FAIL: {r.get('error', 'unknown')}")

print(f"\nOutput folder: {OUT_DIR}")
print("Files:")
for f in sorted(OUT_DIR.iterdir()):
    if f.suffix == ".wav":
        print(f"  - {f.name} ({f.stat().st_size/1024:.0f}KB)")
