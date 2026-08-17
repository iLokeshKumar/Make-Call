"""
Fine-tune XTTS v2 GPT decoder on Aswini's voice.
Requires GPU >= 8GB VRAM. Lower BATCH_SIZE to 1 if OOM.
Run: python xtts_finetune.py
"""
import os
from pathlib import Path

os.environ["COQUI_TOS_AGREED"] = "1"

from trainer import Trainer, TrainerArgs
from TTS.config.shared_configs import BaseDatasetConfig
from TTS.tts.configs.xtts_config import XttsConfig
from TTS.tts.datasets import load_tts_samples
from TTS.tts.models.xtts import Xtts, XttsAudioConfig, XttsArgs
from TTS.utils.manage import ModelManager


def aswini_formatter(root_path, meta_file, **kwargs):
    """Reads pipe-delimited metadata: filename|text (2-column, no header)."""
    items = []
    with open(meta_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            cols = line.split("|")
            if len(cols) < 2:
                continue
            wav_path = str(Path(root_path) / "wavs" / (cols[0].strip() + ".wav"))
            text = cols[1].strip()
            items.append({
                "text": text,
                "audio_file": wav_path,
                "speaker_name": "aswini",
                "root_path": root_path,
            })
    return items

ROOT = Path(__file__).parent
DATASET_DIR = ROOT / "dataset"
OUT_DIR = ROOT / "xtts_finetuned"
LANGUAGE = "en"
BATCH_SIZE = 2  # reduce to 1 if GPU OOM
EPOCHS = 300    # increase for better quality; ~300 for production

OUT_DIR.mkdir(exist_ok=True)

# Download or locate cached XTTS v2 base model
print("Loading XTTS v2 base model...")
model_manager = ModelManager()
model_path, config_path, _ = model_manager.download_model(
    "tts_models/multilingual/multi-dataset/xtts_v2"
)
print(f"Model path: {model_path}")

config = XttsConfig(
    output_path=str(OUT_DIR),
    model_args=XttsArgs(
        gpt_use_perceiver_resampler=True,
    ),
    audio=XttsAudioConfig(
        sample_rate=22050,
        output_sample_rate=24000,
    ),
    batch_size=BATCH_SIZE,
    eval_batch_size=1,
    num_loader_workers=0,
    eval_split_size=0.1,
    print_step=50,
    plot_step=100,
    log_model_step=1000,
    save_step=5000,
    save_n_checkpoints=2,
    save_checkpoints=True,
    print_eval=False,
    use_phonemes=False,
    languages=[LANGUAGE],
    epochs=EPOCHS,
    datasets=[
        BaseDatasetConfig(
            formatter="aswini",
            dataset_name="aswini",
            path=str(DATASET_DIR),
            meta_file_train=str(DATASET_DIR / "metadata.csv"),
            meta_file_val="",
            language=LANGUAGE,
        )
    ],
)

train_samples, eval_samples = load_tts_samples(
    config.datasets,
    eval_split=True,
    eval_split_size=config.eval_split_size,
    formatter=aswini_formatter,
)
print(f"Train: {len(train_samples)} | Eval: {len(eval_samples)} samples")

model = Xtts.init_from_config(config)
model.load_checkpoint(config, checkpoint_dir=model_path, eval=False)

# Only train GPT decoder — freeze DVAE, vocoder, speaker encoder
for name, param in model.named_parameters():
    if "gpt" not in name:
        param.requires_grad = False

trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
total = sum(p.numel() for p in model.parameters())
print(f"Trainable: {trainable:,} / {total:,} params")

trainer = Trainer(
    TrainerArgs(
        restore_path=None,
        skip_train_epoch=False,
        start_with_eval=True,
        grad_clip=0.5,
    ),
    config,
    output_path=str(OUT_DIR),
    model=model,
    train_samples=train_samples,
    eval_samples=eval_samples,
)

trainer.fit()
print(f"\nDone. Checkpoints saved to: {OUT_DIR}")