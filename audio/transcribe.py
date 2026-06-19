import whisper, os, csv

model = whisper.load_model("base")
wavs = [f for f in os.listdir("wavs") if f.endswith(".wav")]

with open("metadata.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, delimiter="|")
        for wav in sorted(wavs):
            result = model.transcribe(f"wavs/{wav}")
            text = result["text"].strip()
            name = wav.replace(".wav", "")
            writer.writerow([name, text])
            print(f"{name} {wav}: {text}")

print("Done! Check metadata.csv for the transcriptions.")

import os
import json
from pathlib import Path
from faster_whisper import WhisperModel

SEGMENTS_DIR = r"E:\something_new\audio\dataset\wavs"
OUTPUT_FILE = r"E:\something_new\audio\dataset.jsonl"

# "medium" is a good balance of speed vs accuracy on CPU
# Use "large-v3" for best accuracy (slower)
model = WhisperModel("medium", device="cpu", compute_type="int8")

results = []
seg_files = sorted(Path(SEGMENTS_DIR).glob("*.wav"))
total = len(seg_files)

for i, wav_file in enumerate(seg_files):
    print(f"[{i+1}/{total}] Transcribing: {wav_file.name}")
    segments, info = model.transcribe(
        str(wav_file),
        beam_size=5,
        language="en",          # change to your language code if not English
        vad_filter=True,        # removes silence at edges
    )
    text = " ".join(seg.text.strip() for seg in segments).strip()

    if len(text) < 5:
        print(f"  → Skipping (transcription too short): '{text}'")
        continue

    results.append({
        "audio_path": str(wav_file),
        "text": text,
        "duration": info.duration
    })
    print(f"  → {text[:80]}")

# Save dataset
with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    for item in results:
        f.write(json.dumps(item) + "\n")

print(f"\nDataset saved: {len(results)} samples → {OUTPUT_FILE}")