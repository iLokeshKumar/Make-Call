"""
F5-TTS Demo for tomorrow's presentation.

Uses the CLEAN recorded audio as reference with the EXACT text
from voice_recording_script.md as reference text.

Usage:
    backend/myenvironment/Scripts/python.exe audio/f5_demo.py

Output:
    audio/f5_demo_output/*.wav
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
import torchaudio

# ---- F5-TTS needs this shim for Windows torchaudio ----
def _sf_load(path, *a, **kw):
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T), sr

torchaudio.load = _sf_load

from f5_tts.api import F5TTS

# ---- Paths ----
ROOT = Path(__file__).resolve().parent
NORMALIZED = ROOT / "my_voice_recordings" / "normalized"
OUT_DIR = ROOT / "f5_demo_output"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---- Reference audio + its exact transcript ----
# These map recording filenames to the matching script text from voice_recording_script.md
# We use the English files since they have the clearest script mapping.

REFERENCES = [
    {
        "name": "expressive_emotion",
        "wav": NORMALIZED / "lk_expressive.wav",
        "text": (
            "That is good to hear. "
            "Oh, I see. I did not know that. "
            "I understand. In that case, we should not rush the decision. "
            "Let us check the requirement properly and then suggest the right product. "
            "No worries. We can wait until you are ready. "
            "I would not recommend that model for heavy commercial usage. "
            "It may work for a short time, but it may not be reliable in the long run. "
            "If you share the approximate size of the room, I can suggest the screen size. "
            "You do not have to decide immediately. "
            "I will send the details, and you can review them whenever you are free."
        ),
        "duration_sec": 65.7,
    },
    {
        "name": "intro_warm",
        "wav": NORMALIZED / "lk_intro.wav",
        "text": (
            "Hello, good morning. I hope you are doing well today. "
            "My name is Ashwini, and I am calling from Yexis Electronics. "
            "We are regional distributors for Samsung products, including commercial displays, signage boards, video walls, monitors, televisions, and air conditioning solutions. "
            "Is this a good time to speak with you for a minute? "
            "I will keep this very brief. "
            "I just wanted to understand whether you have any current or future requirement for displays, signage, video walls, or professional monitors. "
            "Are you currently using Samsung products in your office or factory? "
            "No problem at all. I completely understand. "
            "I can send you a short company profile on WhatsApp or email, whichever is convenient for you. "
            "Please let me know the right email address, and I will share the details. "
            "Thank you for your time. I really appreciate it. "
            "Have a good day."
        ),
        "duration_sec": 279.98,
    },
    {
        "name": "paragraph_long",
        "wav": NORMALIZED / "lk_paragraph.wav",
        "text": (
            "Let me explain this simply. If you need a display for a boardroom, the main things to consider are screen size, brightness, connectivity, and how many hours the display will run each day. For a small meeting room, a fifty five inch or sixty five inch screen may be enough. For a larger conference room, we may need seventy five inch or eighty five inch, depending on the viewing distance. "
            "For signage, the requirement is different. The display may have to run for ten to sixteen hours a day, sometimes even longer. In that case, commercial displays are better than normal televisions because they are designed for longer usage, better heat handling, and business environments. "
            "I am not saying you must buy the most expensive model. I am saying we should choose the right model for the right usage. That way, you do not overspend, and you also do not face problems later."
        ),
        "duration_sec": 207.92,
    },
]

# ---- Sentences to generate for the demo ----
DEMO_SENTENCES = [
    # Short & punchy — good for first impression
    "Hello, good morning. This is Ashwini calling from Yexis Electronics.",
    
    # Medium — shows natural sentence flow
    "I just wanted to check whether you had a chance to look at the details I shared earlier this week.",
    
    # Product-specific — demonstrates domain vocabulary
    "The screen sizes available are forty three inch, fifty five inch, sixty five inch, and seventy five inch for commercial displays.",
    
    # Longer — tests prosody and naturalness
    "Let me explain this simply. If you need a display for a boardroom, the main things to consider are screen size, brightness, connectivity, and how many hours the display will run each day.",
    
    # Follow-up — shows conversational use case
    "Thank you sir. I will wait for your confirmation. Please let me know if you need a revised quote.",
]

# ---- Minimal check: verify files exist ----
for ref in REFERENCES:
    if not ref["wav"].exists():
        print(f"❌ Missing reference WAV: {ref['wav']}")
        print("   Available normalized files:")
        for w in sorted(NORMALIZED.glob("*.wav")):
            print(f"   - {w.name}")
        sys.exit(1)

# ---- Load F5-TTS ----
print("Loading F5-TTS (this may take a minute on CPU)...")
start = time.time()
tts = F5TTS()
print(f"Loaded in {time.time() - start:.1f}s")

# ---- Generate ----
results = []

print("\n" + "=" * 60)
print("F5-TTS DEMO GENERATION")
print("=" * 60)

for ref in REFERENCES:
    ref_name = ref["name"]
    ref_wav = ref["wav"]
    ref_text = ref["text"]
    ref_duration = ref["duration_sec"]

    print(f"\n--- Reference: {ref_name} ({ref_wav.name}, {ref_duration}s) ---")

    for i, gen_text in enumerate(DEMO_SENTENCES):
        out_name = f"demo_{ref_name}_{i:02d}.wav"
        out_path = OUT_DIR / out_name

        if out_path.exists():
            print(f"  [{i+1}/{len(DEMO_SENTENCES)}] {out_name} (already exists, skipping)")
            results.append({
                "ref": ref_name,
                "sentence": gen_text,
                "output": str(out_path),
                "status": "cached",
            })
            continue

        print(f"  [{i+1}/{len(DEMO_SENTENCES)}] Generating: '{gen_text[:50]}...' ", end="", flush=True)
        gen_start = time.time()
        try:
            tts.infer(
                ref_file=str(ref_wav),
                ref_text=ref_text,
                gen_text=gen_text,
                file_wave=str(out_path),
                show_info=print,
            )
            elapsed = time.time() - gen_start
            size_kb = out_path.stat().st_size / 1024
            print(f"OK {elapsed:.1f}s, {size_kb:.0f}KB")
            results.append({
                "ref": ref_name,
                "sentence": gen_text,
                "output": str(out_path),
                "status": "generated",
                "time_sec": round(elapsed, 1),
                "size_kb": round(size_kb, 0),
            })
        except Exception as e:
            print(f"FAILED: {e}")
            results.append({
                "ref": ref_name,
                "sentence": gen_text,
                "output": "",
                "status": "error",
                "error": str(e),
            })

# ---- Summary ----
print("\n" + "=" * 60)
print("DEMO SUMMARY")
print("=" * 60)

generated = [r for r in results if r["status"] == "generated"]
errors = [r for r in results if r["status"] == "error"]
cached = [r for r in results if r["status"] == "cached"]

print(f"Generated: {len(generated)} files")
print(f"Cached (already existed): {len(cached)} files")
print(f"Errors: {len(errors)} files")

if generated:
    total_time = sum(r.get("time_sec", 0) for r in generated)
    print(f"Total generation time: {total_time:.1f}s")
    print(f"Average per file: {total_time/len(generated):.1f}s")

print(f"\nAll outputs in: {OUT_DIR}")
print("\nFiles generated:")
for r in results:
    if r["status"] in ("generated", "cached"):
        print(f"  ✓ {Path(r['output']).name}  |  '{r['sentence'][:60]}...'")

if errors:
    print("\nErrors:")
    for r in errors:
        print(f"  ✗ {r['ref']}: {r.get('error', 'unknown')}")

# Write a simple HTML demo page
html_path = OUT_DIR / "demo_player.html"
html_content = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>F5-TTS Demo</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 800px; margin: 0 auto; padding: 20px; }
  .ref { margin: 24px 0; padding: 16px; border: 1px solid #ddd; border-radius: 8px; }
  .ref h3 { margin: 0 0 8px; color: #333; }
  .clip { display: flex; align-items: center; gap: 12px; margin: 8px 0; padding: 8px; background: #f5f5f5; border-radius: 6px; }
  .clip audio { flex: 1; }
  .clip .label { flex: 2; font-size: 14px; color: #555; }
</style></head><body>
<h1>F5-TTS Voice Clone Demo</h1>
"""
for ref_name in set(r['ref'] for r in results):
    ref_results = [r for r in results if r['ref'] == ref_name and r['status'] in ('generated', 'cached')]
    if not ref_results:
        continue
    html_content += f'<div class="ref"><h3>Reference: {ref_name}</h3>\n'
    for r in ref_results:
        fname = Path(r['output']).name
        html_content += f'<div class="clip"><span class="label">{r["sentence"][:80]}</span><audio controls src="{fname}"></audio></div>\n'
    html_content += '</div>\n'
html_content += "</body></html>"

html_path.write_text(html_content, encoding="utf-8")

print(f"\nDemo player HTML: {html_path}")
print("Open that in Chrome to play all generations side by side.")
