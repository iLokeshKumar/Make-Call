import os
from pydub import AudioSegment
from pydub.silence import split_on_silence
from pathlib import Path

INPUT_DIR = r"E:\something_new\audio\wavs"
OUTPUT_DIR = r"E:\something_new\audio\dataset\wavs"
MIN_DURATION_MS = 3000   # 3 seconds minimum
MAX_DURATION_MS = 15000  # 15 seconds maximum

os.makedirs(OUTPUT_DIR, exist_ok=True)
count = 0

for wav_file in Path(INPUT_DIR).glob("*.wav"):
    print(f"Segmenting: {wav_file.name}")
    audio = AudioSegment.from_wav(str(wav_file))

    # Split on silence
    chunks = split_on_silence(
        audio,
        min_silence_len=400,     # silence gap in ms to cut on
        silence_thresh=-40,      # dBFS — adjust if clips too long/short
        keep_silence=150,        # padding around cuts
    )

    for chunk in chunks:
        duration = len(chunk)
        if duration < MIN_DURATION_MS:
            continue  # too short, skip
        if duration > MAX_DURATION_MS:
            # split long chunks into 10s pieces
            for start in range(0, duration, 10000):
                piece = chunk[start:start+10000]
                if len(piece) < MIN_DURATION_MS:
                    continue
                out_path = os.path.join(OUTPUT_DIR, f"seg_{count:05d}.wav")
                piece.export(out_path, format="wav")
                count += 1
        else:
            out_path = os.path.join(OUTPUT_DIR, f"seg_{count:05d}.wav")
            chunk.export(out_path, format="wav")
            count += 1

print(f"Total segments: {count}")