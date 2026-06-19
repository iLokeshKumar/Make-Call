import os
from pydub import AudioSegment
from pathlib import Path

INPUT_DIR = r"E:\something_new\audio\w_audio"
OUTPUT_DIR = r"E:\something_new\audio\wavs"

os.makedirs(OUTPUT_DIR, exist_ok=True)

for file in Path(INPUT_DIR).iterdir():
    if file.suffix.lower() in [".wav", ".mp3", ".m4a", ".flac", ".ogg", ".aac", ".mpeg"]:
        print(f"Converting: {file.name}")
        audio = AudioSegment.from_file(str(file))
        audio = audio.set_channels(1)          # mono
        audio = audio.set_frame_rate(24000)    # 24kHz — Orpheus requirement
        out_path = os.path.join(OUTPUT_DIR, file.stem + ".wav")
        audio.export(out_path, format="wav")
        print(f"  → Saved: {out_path}")

print("Done converting.")