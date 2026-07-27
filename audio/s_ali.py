from pathlib import Path
import sys

import torchaudio


ROOT = Path(__file__).resolve().parent
MODEL_DIR = ROOT / "pretrained_models" / "CosyVoice2-0.5B"
PROMPT_AUDIO = ROOT / "lk_expressive.wav"
OUTPUT_AUDIO = ROOT / "output.wav"


# Official FunAudioLLM/CosyVoice needs third_party/Matcha-TTS on sys.path.
# This keeps the script working if the repo is cloned beside this file.
LOCAL_COSYVOICE_REPO = ROOT / "CosyVoice"
MATCHA_TTS = LOCAL_COSYVOICE_REPO / "third_party" / "Matcha-TTS"
if MATCHA_TTS.exists():
    sys.path.insert(0, str(MATCHA_TTS))
if LOCAL_COSYVOICE_REPO.exists():
    sys.path.insert(0, str(LOCAL_COSYVOICE_REPO))

try:
    from cosyvoice.cli.cosyvoice import AutoModel
except ModuleNotFoundError as exc:
    if exc.name and exc.name.startswith("cosyvoice"):
        raise SystemExit(
            "This script needs the official FunAudioLLM/CosyVoice repo/package. "
            "The PyPI package 'cosyvoice==0.0.8' installed in your environment "
            "does not include cosyvoice.cli.\n\n"
            "Setup:\n"
            "  cd E:\\something_new\\audio\n"
            "  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git\n"
            "  cd CosyVoice\n"
            "  pip install -r requirements.txt\n"
            "  cd ..\n"
            "  python -c \"from huggingface_hub import snapshot_download; "
            "snapshot_download('FunAudioLLM/CosyVoice2-0.5B', "
            "local_dir='pretrained_models/CosyVoice2-0.5B')\"\n"
            "  python s_ali.py"
        ) from exc
    raise


def main() -> None:
    if not MODEL_DIR.exists():
        raise SystemExit(f"Missing model directory: {MODEL_DIR}")
    if not PROMPT_AUDIO.exists():
        raise SystemExit(f"Missing prompt audio: {PROMPT_AUDIO}")

    model = AutoModel(model_dir=str(MODEL_DIR))

    for index, result in enumerate(
        model.inference_zero_shot(
            "Hello, this is Lokesh calling from Yexis Electronics.",
            "This is what Lokesh said in the reference audio",
            str(PROMPT_AUDIO),
            stream=False,
        )
    ):
        output_path = OUTPUT_AUDIO if index == 0 else ROOT / f"output_{index}.wav"
        torchaudio.save(str(output_path), result["tts_speech"], model.sample_rate)
        print(f"Saved {output_path}")


if __name__ == "__main__":
    main()
