"""
Dataset preparation pipeline:
  MPEG recordings → WhisperX (word timestamps + diarization) →
  filter Aswini's English turns → slice WAVs → dataset.jsonl

Requirements:
  pip install whisperx pyannote.audio soundfile langdetect
  ffmpeg must be on PATH

Usage:
  python prepare_dataset.py --hf_token YOUR_HF_TOKEN
"""

import argparse
import json
import os
import subprocess
import sys

import soundfile as sf
import torch
from dotenv import load_dotenv

load_dotenv(r"E:\something_new\backend\.env")

AUDIO_DIR   = r"E:\something_new\audio\w_audio"
OUT_WAV_DIR = r"E:\something_new\audio\dataset_v2\wavs"
OUT_JSONL   = r"E:\something_new\audio\dataset_v2\dataset.jsonl"

MIN_SEC = 2.5
MAX_SEC = 8.0
MIN_WORDS = 4


def convert_to_wav(src: str, dst: str):
    subprocess.run(
        ["ffmpeg", "-y", "-i", src, "-ar", "16000", "-ac", "1", dst],
        check=True, capture_output=True,
    )


def is_english(text: str) -> bool:
    try:
        from langdetect import detect
        return detect(text) == "en"
    except Exception:
        return False


def dominant_speaker(segments) -> str:
    """Return speaker ID with most total speaking time."""
    durations: dict[str, float] = {}
    for seg in segments:
        spk = seg.get("speaker", "")
        dur = seg["end"] - seg["start"]
        durations[spk] = durations.get(spk, 0) + dur
    return max(durations, key=durations.get) if durations else ""


def process_file(wav_path: str, hf_token: str, model, diarize_model):
    import whisperx

    audio = whisperx.load_audio(wav_path)
    result = model.transcribe(audio, batch_size=8, language="en")

    # whisperx.DiarizationPipeline accepts numpy array directly (no torchcodec)
    # and returns a DataFrame that assign_word_speakers expects
    diarize_segments = diarize_model(audio, min_speakers=2, max_speakers=3)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    return result["segments"]


def slice_and_save(wav_path: str, segments, target_speaker: str, out_dir: str, prefix: str):
    import numpy as np

    audio, sr = sf.read(wav_path)
    samples = []
    idx = 0
    for seg in segments:
        spk = seg.get("speaker", "")
        if spk != target_speaker:
            continue
        text = seg.get("text", "").strip()
        dur = seg["end"] - seg["start"]
        if dur < MIN_SEC or dur > MAX_SEC:
            continue
        if len(text.split()) < MIN_WORDS:
            continue
        if not is_english(text):
            continue

        start_s = int(seg["start"] * sr)
        end_s   = int(seg["end"]   * sr)
        chunk   = audio[start_s:end_s]

        filename = f"{prefix}_{idx:04d}.wav"
        out_path = os.path.join(out_dir, filename)
        sf.write(out_path, chunk, sr)
        samples.append({"audio_path": out_path, "text": text})
        idx += 1

    return samples


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hf_token", default=os.getenv("HF_TOKEN"))
    parser.add_argument("--whisper_model", default="base")
    args = parser.parse_args()

    if not args.hf_token:
        sys.exit("HF_TOKEN not found in .env and not passed via --hf_token")

    os.makedirs(OUT_WAV_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(OUT_JSONL), exist_ok=True)

    mpeg_files = [
        f for f in os.listdir(AUDIO_DIR)
        if f.lower().endswith(".mpeg") or f.lower().endswith(".mp3")
    ]

    tmp_wav_dir = os.path.join(AUDIO_DIR, "_tmp_wavs")
    os.makedirs(tmp_wav_dir, exist_ok=True)

    # Convert all files before loading models — avoids WinError 1455 (paging file
    # too small to spawn ffmpeg subprocess after large models are in memory)
    print("Converting MPEG files to WAV...")
    wav_jobs = []
    for mpeg in sorted(mpeg_files):
        src = os.path.join(AUDIO_DIR, mpeg)
        prefix = os.path.splitext(mpeg)[0].replace(" ", "_")
        tmp_wav = os.path.join(tmp_wav_dir, prefix + ".wav")
        if not os.path.exists(tmp_wav):
            convert_to_wav(src, tmp_wav)
        wav_jobs.append((mpeg, prefix, tmp_wav))

    import whisperx
    from whisperx.diarize import DiarizationPipeline

    print("Loading WhisperX model...")
    model = whisperx.load_model(args.whisper_model, "cpu", compute_type="int8")

    print("Loading diarization pipeline...")
    diarize_model = DiarizationPipeline(token=args.hf_token, device="cpu")

    all_samples = []

    for mpeg, prefix, tmp_wav in wav_jobs:
        print(f"\n{'='*60}")
        print(f"Processing: {mpeg}")

        print("  Transcribing + diarizing...")
        try:
            segments = process_file(tmp_wav, args.hf_token, model, diarize_model)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        if not segments:
            print("  No segments found, skipping.")
            continue

        # Aswini = dominant speaker (she talks most as salesperson)
        target_spk = dominant_speaker(segments)
        print(f"  Target speaker (Aswini): {target_spk}")

        samples = slice_and_save(tmp_wav, segments, target_spk, OUT_WAV_DIR, prefix)
        print(f"  Saved {len(samples)} clean segments")
        all_samples.extend(samples)

    with open(OUT_JSONL, "w") as f:
        for item in all_samples:
            f.write(json.dumps(item) + "\n")

    print(f"\nDone. Total samples: {len(all_samples)}")
    print(f"JSONL: {OUT_JSONL}")
    print(f"WAVs:  {OUT_WAV_DIR}")


if __name__ == "__main__":
    main()
