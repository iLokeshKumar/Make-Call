"""
Interactive XTTS v2 voice cloning CLI.
Loads fine-tuned checkpoint if available, else uses base model.
Run: python clone.py
"""
import os
import glob
import torch
from pathlib import Path
from TTS.api import TTS

os.environ["COQUI_TOS_AGREED"] = "1"

ROOT = Path(__file__).parent
WAVS_DIR = ROOT / "wavs"
FINETUNED_DIR = ROOT / "xtts_finetuned"
LANGUAGES = ["en", "hi", "fr", "de", "es", "pt", "ja", "zh-cn", "ar"]


def pick_speaker_wav() -> str:
    wavs = sorted(WAVS_DIR.glob("*.wav"))
    if not wavs:
        raise FileNotFoundError(f"No WAV files in {WAVS_DIR}")

    print("\nAvailable speaker WAVs:")
    for i, w in enumerate(wavs):
        size_kb = w.stat().st_size // 1024
        print(f"  [{i}] {w.name}  ({size_kb} KB)")

    while True:
        choice = input(f"\nPick speaker [0-{len(wavs)-1}] (Enter = 0): ").strip()
        if choice == "":
            return str(wavs[0])
        if choice.isdigit() and 0 <= int(choice) < len(wavs):
            return str(wavs[int(choice)])
        print("  Invalid choice.")


def pick_language() -> str:
    print("\nLanguages:", " | ".join(f"[{i}]{l}" for i, l in enumerate(LANGUAGES)))
    while True:
        choice = input(f"Pick language [0-{len(LANGUAGES)-1}] (Enter = 0 = en): ").strip()
        if choice == "":
            return LANGUAGES[0]
        if choice.isdigit() and 0 <= int(choice) < len(LANGUAGES):
            return LANGUAGES[int(choice)]
        print("  Invalid choice.")


def load_model() -> TTS:
    print("\nLoading XTTS v2...")
    tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")

    checkpoints = sorted(glob.glob(str(FINETUNED_DIR / "**/*.pth"), recursive=True))
    if checkpoints:
        ckpt = checkpoints[-1]
        print(f"Fine-tuned checkpoint found: {ckpt}")
        state = torch.load(ckpt, map_location="cpu")
        if "model" in state:
            tts.synthesizer.tts_model.load_state_dict(state["model"], strict=False)
            print("Fine-tuned weights loaded.")
        else:
            print("Checkpoint format unrecognised — using base model.")
    else:
        print("No fine-tuned checkpoint found — using base XTTS v2.")

    return tts


def main():
    print("=" * 50)
    print("  XTTS v2 Voice Cloning — Aswini / Yexis")
    print("=" * 50)

    tts = load_model()
    speaker_wav = pick_speaker_wav()
    language = pick_language()

    session = 1
    while True:
        print(f"\n--- Synthesis #{session} ---")
        text = input("Text (Enter to quit): ").strip()
        if not text:
            print("Exiting.")
            break

        out_path = ROOT / f"output_{session}.wav"
        print(f"Generating → {out_path.name} ...")

        tts.tts_to_file(
            text=text,
            speaker_wav=speaker_wav,
            language=language,
            file_path=str(out_path),
        )
        print(f"Saved: {out_path}")
        session += 1

        again = input("Change speaker/language? [y/N]: ").strip().lower()
        if again == "y":
            speaker_wav = pick_speaker_wav()
            language = pick_language()


if __name__ == "__main__":
    main()
