"""
XTTS v2 Voice Clone Demo — using CLEAN recordings as reference.

Usage:
    audio/tts_env/Scripts/python.exe audio/xtts_demo.py

Output:
    audio/xtts_demo_output/*.wav
"""

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
NORMALIZED = ROOT / "my_voice_recordings" / "normalized"
OUT_DIR = ROOT / "xtts_demo_output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# Use the SHORTEST clean English recording as reference
# lk_expressive.wav is 65.7s — shortest English one
REF_WAV = NORMALIZED / "lk_expressive.wav"

# Also try a short clip from the intro as a second option
REF_INTRO = NORMALIZED / "lk_intro.wav"

print("=" * 50)
print("XTTS v2 VOICE CLONE DEMO")
print("=" * 50)
print(f"Reference: {REF_WAV.name}")
print(f"Reference exists: {REF_WAV.exists()}")
print()

# Test sentences for demo
DEMO_TEXTS = [
    "Hello, good morning. This is Ashwini calling from Yexis Electronics.",
    "I just wanted to check whether you had a chance to look at the details.",
    "Thank you for your time. I really appreciate it.",
]

print("Loading XTTS v2 model...")
print("(First run downloads ~1.2GB model, may take a few minutes)")
start = time.time()
sys.stdout.flush()

# PyTorch 2.6+ weights_only=True blocks XTTS config loading
# Simpler fix: patch torch.load to use weights_only=False
import torch
_orig_torch_load = torch.load
torch.load = lambda f, *a, **kw: _orig_torch_load(f, *a, **{**kw, 'weights_only': kw.get('weights_only', False)})

from TTS.api import TTS

tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)
load_time = time.time() - start
print(f"Model loaded in {load_time:.1f}s")
print()

for i, text in enumerate(DEMO_TEXTS):
    out_path = OUT_DIR / f"xtts_en_{i:02d}.wav"
    if out_path.exists():
        print(f"[{i+1}/{len(DEMO_TEXTS)}] {out_path.name} exists, skipping")
        continue

    print(f"[{i+1}/{len(DEMO_TEXTS)}] Generating: '{text}'")
    print(f"  (may take a while on CPU...)", flush=True)
    gen_start = time.time()
    try:
        tts.tts_to_file(
            text=text,
            speaker_wav=str(REF_WAV),
            language="en",
            file_path=str(out_path),
        )
        elapsed = time.time() - gen_start
        size_kb = out_path.stat().st_size / 1024
        print(f"  Done in {elapsed:.1f}s, {size_kb:.0f}KB")
    except Exception as e:
        print(f"  FAILED: {e}")
        # Try shorter ref as fallback
        try:
            print(f"  Retrying with different reference...")
            out_path2 = OUT_DIR / f"xtts_en_{i:02d}_v2.wav"
            tts.tts_to_file(
                text=text,
                speaker_wav=str(REF_INTRO),
                language="en",
                file_path=str(out_path2),
            )
            print(f"  Done with v2 in {time.time() - gen_start:.1f}s")
        except Exception as e2:
            print(f"  FAILED again: {e2}")

print()
print("=" * 50)
print("FILES GENERATED:")
for f in sorted(OUT_DIR.glob("*.wav")):
    print(f"  {f.name}  ({f.stat().st_size/1024:.0f}KB)")
print(f"\nOutput folder: {OUT_DIR}")
