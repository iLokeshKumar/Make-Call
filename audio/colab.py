"""
Orpheus voice-cloning Colab cells — cleaned up
===============================================
All Drive files live in ONE folder: MyDrive/rio/

Before starting:
  1. Runtime → Change runtime type → T4 GPU
  2. Upload to MyDrive/rio/:
       dataset.zip   (contains wavs/ folder + dataset.jsonl inside)
  3. Run cells IN ORDER: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
  4. After Cell 8 completes, download:
       MyDrive/rio/orpheus_aswini.gguf
  5. Update ORPHEUS_GGUF_PATH in test_tts.py to point to that file

SPEAKER_NAME = "Aswini"  ← must match EXACTLY in Cell 5 and test_tts.py
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 1 — Install (run once per session)
# ═══════════════════════════════════════════════════════════════════════════
CELL_1 = """
!pip install -q unsloth snac torchaudio datasets transformers accelerate trl
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 2 — Mount Drive
# ═══════════════════════════════════════════════════════════════════════════
CELL_2 = """
from google.colab import drive
drive.mount('/content/drive')

import os
DRIVE = "/content/drive/MyDrive/rio"
os.makedirs(DRIVE, exist_ok=True)
print("Drive folder:", DRIVE)
print("Contents:", os.listdir(DRIVE))
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 3 — Unzip dataset
# Expects: MyDrive/rio/dataset.zip
# The zip must contain:
#   wavs/seg_*.wav        (audio segments)
#   dataset.jsonl         (transcriptions)
# ═══════════════════════════════════════════════════════════════════════════
CELL_3 = """
import zipfile, os, json

DRIVE    = "/content/drive/MyDrive/rio"
ZIP_PATH = f"{DRIVE}/dataset.zip"
WORK_DIR = "/content/work"
WAV_DIR  = f"{WORK_DIR}/wavs"

os.makedirs(WORK_DIR, exist_ok=True)

print("Extracting", ZIP_PATH, "...")
with zipfile.ZipFile(ZIP_PATH, 'r') as z:
    z.extractall(WORK_DIR)

# Find dataset.jsonl — may be at root or in a subfolder
jsonl_path = None
for root, dirs, files in os.walk(WORK_DIR):
    for f in files:
        if f == "dataset.jsonl":
            jsonl_path = os.path.join(root, f)
            break

# Find wavs dir
wavs_path = None
for root, dirs, files in os.walk(WORK_DIR):
    for d in dirs:
        if d == "wavs":
            wavs_path = os.path.join(root, d)
            break
    if wavs_path:
        break

if wavs_path is None:
    # Flat zip — wavs directly in WORK_DIR
    wavs_path = WORK_DIR

print(f"WAVs at: {wavs_path}  ({len(os.listdir(wavs_path))} files)")

if jsonl_path:
    print(f"dataset.jsonl at: {jsonl_path}")
    with open(jsonl_path) as f:
        samples = [json.loads(l) for l in f if l.strip()]
    print(f"Transcriptions: {len(samples)}")
else:
    print("WARNING: dataset.jsonl not found inside zip")
    print("  Place it at MyDrive/rio/dataset.jsonl manually")
    jsonl_path = f"{DRIVE}/dataset.jsonl"
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 4 — Encode audio → 7-token SNAC integer list
# Output: MyDrive/rio/tokenized.jsonl
# ═══════════════════════════════════════════════════════════════════════════
CELL_4 = """
import json, os, torch, torchaudio
from snac import SNAC
from pathlib import Path
from tqdm import tqdm

DRIVE       = "/content/drive/MyDrive/rio"
WORK_DIR    = "/content/work"
MAX_AUDIO_S = 8   # skip clips longer than this (8192 ctx fits ~7.5s)

snac_model = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval().cuda()

def audio_to_tokens(wav_path):
    waveform, sr = torchaudio.load(wav_path)
    if sr != 24000:
        waveform = torchaudio.functional.resample(waveform, sr, 24000)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(0, keepdim=True)
    if waveform.shape[-1] / 24000 > MAX_AUDIO_S:
        return None
    with torch.no_grad():
        codes = snac_model.encode(waveform.unsqueeze(0).cuda())
    c0 = codes[0].squeeze().cpu().tolist()
    c1 = codes[1].squeeze().cpu().tolist()
    c2 = codes[2].squeeze().cpu().tolist()
    if len(c1) < 2 * len(c0) or len(c2) < 4 * len(c0):
        return None
    tokens = []
    for i in range(len(c0)):
        tokens.append(c0[i])
        tokens.append(c1[2*i]     + 4096)
        tokens.append(c2[4*i]     + 8192)
        tokens.append(c2[4*i+1]   + 12288)
        tokens.append(c1[2*i+1]   + 16384)
        tokens.append(c2[4*i+2]   + 20480)
        tokens.append(c2[4*i+3]   + 24576)
    return tokens

# Locate jsonl and wavs
jsonl_path = None
for root, dirs, files in os.walk(WORK_DIR):
    for f in files:
        if f == "dataset.jsonl":
            jsonl_path = os.path.join(root, f)
            break
if jsonl_path is None:
    jsonl_path = f"{DRIVE}/dataset.jsonl"

wavs_path = None
for root, dirs, files in os.walk(WORK_DIR):
    for d in dirs:
        if d == "wavs":
            wavs_path = os.path.join(root, d)
            break
    if wavs_path:
        break
if wavs_path is None:
    wavs_path = WORK_DIR

print(f"jsonl: {jsonl_path}")
print(f"wavs:  {wavs_path}")

with open(jsonl_path) as f:
    samples = [json.loads(l) for l in f if l.strip()]

tokenized, skipped = [], 0
for item in tqdm(samples, desc="SNAC encoding"):
    filename = Path(item["audio_path"].replace("\\\\", "/")).name
    wav_path = os.path.join(wavs_path, filename)
    if not os.path.exists(wav_path):
        skipped += 1
        continue
    try:
        tokens = audio_to_tokens(wav_path)
        if tokens is None or len(tokens) < 14:
            skipped += 1
            continue
        tokenized.append({"text": item["text"], "tokens": tokens})
    except Exception as e:
        print(f"  {filename}: {e}")
        skipped += 1

print(f"Encoded: {len(tokenized)}  |  skipped: {skipped}")

tok_path = f"{DRIVE}/tokenized.jsonl"
with open(tok_path, "w") as f:
    for item in tokenized:
        f.write(json.dumps(item) + "\\n")
print("Saved:", tok_path)
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 5 — Format dataset as <custom_token_N> training strings
# ═══════════════════════════════════════════════════════════════════════════
CELL_5 = """
import json
from datasets import Dataset

DRIVE        = "/content/drive/MyDrive/rio"
SPEAKER_NAME = "Aswini"   # MUST match test_tts.py exactly

def format_sample(text, tokens):
    audio_str = "".join(f"<custom_token_{t + 10}>" for t in tokens)
    return (
        f"<|im_start|>user\\n"
        f"<custom_token_3>{SPEAKER_NAME}: {text}<|eot_id|><custom_token_4>\\n"
        f"<|im_end|>\\n"
        f"<|im_start|>assistant\\n"
        f"<custom_token_5>{audio_str}<|im_end|>"
    )

with open(f"{DRIVE}/tokenized.jsonl") as f:
    samples = [json.loads(l) for l in f if l.strip()]

formatted = [{"text": format_sample(s["text"], s["tokens"])} for s in samples]
print(f"Total: {len(formatted)} samples")
print("\\nPreview (first 300 chars):")
print(formatted[0]["text"][:300])
print(f"\\nCustom tokens in sample: {formatted[0]['text'].count('<custom_token_')}")

split = int(len(formatted) * 0.9)
train_dataset = Dataset.from_list(formatted[:split])
val_dataset   = Dataset.from_list(formatted[split:])
print(f"\\nTrain: {len(train_dataset)}  |  Val: {len(val_dataset)}")
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 6 — Fine-tune with Unsloth
# 10 epochs, lr=1e-4 for better convergence on small dataset
# ═══════════════════════════════════════════════════════════════════════════
CELL_6 = """
from unsloth import FastLanguageModel
from trl import SFTTrainer, SFTConfig
import torch

model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="canopylabs/orpheus-3b-0.1-ft",
    max_seq_length=8192,
    dtype=None,
    load_in_4bit=True,
)

model = FastLanguageModel.get_peft_model(
    model,
    r=32,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                    "gate_proj", "up_proj", "down_proj"],
    lora_alpha=16,
    lora_dropout=0.05,
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=42,
)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_dataset,
    eval_dataset=val_dataset,
    args=SFTConfig(
        output_dir="/content/checkpoints",
        num_train_epochs=10,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=8,
        learning_rate=1e-4,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=10,
        eval_steps=50,
        save_steps=200,
        save_total_limit=2,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        optim="adamw_8bit",
        dataset_text_field="text",
        max_seq_length=8192,
        report_to="none",
    ),
)

print("Starting training...")
trainer.train()
print("Done. Final loss above.")
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 7 — Save LoRA adapter
# ═══════════════════════════════════════════════════════════════════════════
CELL_7 = """
DRIVE     = "/content/drive/MyDrive/rio"
LORA_PATH = f"{DRIVE}/lora"
model.save_pretrained(LORA_PATH)
tokenizer.save_pretrained(LORA_PATH)
print("LoRA saved:", LORA_PATH)
"""

# ═══════════════════════════════════════════════════════════════════════════
# CELL 8 — Export GGUF (Q4_K_M, ~2GB)
# Download this file after it finishes
# ═══════════════════════════════════════════════════════════════════════════
CELL_8 = """
DRIVE       = "/content/drive/MyDrive/rio"
MERGED_PATH = "/content/orpheus_merged"
GGUF_PATH   = f"{DRIVE}/orpheus_aswini.gguf"

model.save_pretrained_merged(MERGED_PATH, tokenizer, save_method="merged_16bit")
model.save_pretrained_gguf(GGUF_PATH, tokenizer, quantization_method="q4_k_m")
print("GGUF saved:", GGUF_PATH)
print("Download this file and update ORPHEUS_GGUF_PATH in test_tts.py")
"""
