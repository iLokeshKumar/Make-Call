from pathlib import Path
from TTS.api import TTS

ROOT = Path("E:/something_new/audio")
WAVS = ROOT / "wavs"
OUT = ROOT / "output_cloned.wav"

TEXT = "Hello, this is Aswini from Yexis Electronics. Thank you for your time today."
SPEAKER_WAV = WAVS / "WhatsApp Audio 2026-05-28 at 11.02.52 AM (2).wav"  # clean, ~54s
LANGUAGE = "en"

print("Loading XTTS v2...")
tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=False)

print(f"Cloning voice from: {SPEAKER_WAV.name}")
tts.tts_to_file(
    text=TEXT,
    speaker_wav=str(SPEAKER_WAV),
    language=LANGUAGE,
    file_path=str(OUT),
)
print(f"Saved cloned speech to: {OUT}")