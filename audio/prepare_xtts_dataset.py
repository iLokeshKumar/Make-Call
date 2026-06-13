"""
Split long call recordings into short XTTS-friendly segments.
Output: dataset/wavs/*.wav and dataset/metadata.csv
"""
import os
import csv
import re
from pathlib import Path
from pydub import AudioSegment
from pydub.silence import detect_nonsilent

ROOT = Path("E:/something_new/audio")
SRC_WAVS = ROOT / "wavs"
META = ROOT / "metadata.csv"
OUT_DIR = ROOT / "dataset"
OUT_WAVS = OUT_DIR / "wavs"
OUT_WAVS.mkdir(parents=True, exist_ok=True)

TARGET_SR = 22050
MIN_LEN_MS = 1500   # keep segments >= 1.5s
MAX_LEN_MS = 12000  # cap at 12s

def slugify(name: str) -> str:
    name = re.sub(r"\.wav$", "", name, flags=re.I)
    name = re.sub(r"[^\w\s-]", "", name).strip()
    name = re.sub(r"[-\s]+", "_", name)
    return name

# load transcripts
transcripts = {}
if META.exists():
    with open(META, "r", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter="|")
        for row in reader:
            if len(row) >= 2:
                transcripts[row[0].strip()] = row[1].strip()

rows = []
for wav_file in sorted(SRC_WAVS.glob("*.wav")):
    key = wav_file.stem
    text = transcripts.get(key, "")
    if not text:
        print(f"Skipping {wav_file.name}: no transcript")
        continue

    audio = AudioSegment.from_wav(wav_file)
    if audio.channels > 1:
        audio = audio.set_channels(1)
    if audio.frame_rate != TARGET_SR:
        audio = audio.set_frame_rate(TARGET_SR)
    if audio.sample_width != 2:
        audio = audio.set_sample_width(2)

    # detect speech regions (tune silence/min_len for your audio)
    nonsilent = detect_nonsilent(
        audio,
        min_silence_len=300,
        silence_thresh=audio.dBFS - 14.0,
    )

    chunk_idx = 0
    for start, end in nonsilent:
        # chunk too long? split into MAX_LEN_MS windows
        cursor = start
        while cursor < end:
            seg_end = min(cursor + MAX_LEN_MS, end)
            if seg_end - cursor < MIN_LEN_MS:
                cursor = seg_end
                continue
            segment = audio[cursor:seg_end]
            out_name = f"{slugify(key)}_{chunk_idx:04d}.wav"
            out_path = OUT_WAVS / out_name
            segment.export(out_path, format="wav", parameters=["-ac", "1", "-ar", str(TARGET_SR)])
            # rough transcript chunking: distribute words evenly
            words = text.split()
            ratio_start = cursor / len(audio)
            ratio_end = seg_end / len(audio)
            w_start = int(ratio_start * len(words))
            w_end = int(ratio_end * len(words))
            seg_text = " ".join(words[w_start:w_end]).strip() or text
            rows.append((out_name.replace(".wav", ""), seg_text))
            chunk_idx += 1
            cursor = seg_end
    print(f"{wav_file.name}: {chunk_idx} segments")

with open(OUT_DIR / "metadata.csv", "w", newline="", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter="|")
    writer.writerows(rows)

print(f"Done. {len(rows)} segments written to {OUT_DIR}")
