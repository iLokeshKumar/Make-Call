import numpy as np
import torch
import soundfile as sf
from llama_cpp import Llama
from snac import SNAC

ORPHEUS_GGUF_PATH = r"E:\something_new\audio\orpheus_aswini_q4.gguf"
SPEAKER_NAME = "Aswini"        # must match the name used during Colab training
OUTPUT_WAV   = "output1.wav"
N_THREADS    = 6                 # set to your CPU core count - 2

# Orpheus codec constants (DO NOT CHANGE)
CODEC_OFFSET = 128266  # audio tokens start at this ID in the vocabulary
# 7-token frame: each position has a unique offset so the model learns positional context
# offsets: c0=0, c1_a=4096, c2_a=8192, c2_b=12288, c1_b=16384, c2_c=20480, c2_d=24576
SNAC_POS_OFFSETS = [0, 4096, 8192, 12288, 16384, 20480, 24576]

print("Loading Orpheus GGUF (CPU)...")
llm = Llama(
    model_path=ORPHEUS_GGUF_PATH,
    n_ctx=8192,          # ← was 2048, must be large enough for audio tokens
    n_threads=N_THREADS,
    verbose=False,
)

print("Loading SNAC decoder (CPU)...")
snac_model = SNAC.from_pretrained("hubertsiuzdak/snac_24khz").eval()
print("Models loaded.\n")


def build_orpheus_prompt(text: str, speaker: str) -> str:
    """
    CORRECT Orpheus prompt format.
    The old guide used a made-up format - this is the real one.
    <custom_token_3>, <custom_token_4>, <custom_token_5> are special tokens
    baked into the Orpheus tokenizer.
    """
    return (
        f"<|im_start|>user\n"
        f"<custom_token_3>{speaker}: {text}<|eot_id|><custom_token_4>\n"
        f"<|im_end|>\n"
        f"<|im_start|>assistant\n"
        f"<custom_token_5>"
    )


def generate_audio_tokens(text: str, speaker: str, max_new_tokens: int = 1200):
    """
    Generate audio codec token IDs from the model.
    Audio tokens have IDs >= CODEC_OFFSET. We collect them and subtract the offset.
    """
    prompt = build_orpheus_prompt(text, speaker)
    prompt_ids = llm.tokenize(prompt.encode(), add_bos=True)
    print(f"Prompt length: {len(prompt_ids)} tokens")

    audio_codes = []
    non_audio_sample = []
    total_generated = 0

    for token_id in llm.generate(
        prompt_ids,
        temp=0.6,
        top_p=0.9,
        repeat_penalty=1.0,
    ):
        total_generated += 1
        if token_id == llm.token_eos():
            print(f"  EOS at token {total_generated}")
            break
        if total_generated >= max_new_tokens:
            break
        if token_id >= CODEC_OFFSET:
            audio_codes.append(token_id - CODEC_OFFSET)
        elif len(non_audio_sample) < 10:
            non_audio_sample.append(token_id)

    print(f"Generated {total_generated} tokens total, {len(audio_codes)} audio codes")
    if not audio_codes:
        sample = non_audio_sample[:10]
        print(f"  Non-audio token IDs (first 10): {sample}")
        texts = [llm.detokenize([t]).decode('utf-8', errors='replace') for t in sample]
        print(f"  Decoded: {texts}")
    return audio_codes


def decode_audio(audio_codes: list) -> "np.ndarray | None":
    """
    Orpheus outputs 7-token super-frames with per-position offsets.
    snac_24khz vq_strides=[4,2,1]: needs c0=N, c1=2N, c2=4N so that
    repeat_interleave gives 4N for all three → no size mismatch.

    Frame layout (offsets verified from live model output):
      pos 0: c0          offset 0
      pos 1: c1_a+4096   offset 4096
      pos 2: c2_a+8192   offset 8192
      pos 3: c2_b+12288  offset 12288
      pos 4: c1_b+16384  offset 16384
      pos 5: c2_c+20480  offset 20480
      pos 6: c2_d+24576  offset 24576
    """
    if len(audio_codes) < 7:
        print(f"Too few audio codes ({len(audio_codes)}), cannot decode")
        return None

    # Each value range uniquely identifies which codebook/position it belongs to.
    # This is robust to non-audio tokens scattered through the stream.
    c0, c1, c2 = [], [], []
    for code in audio_codes:
        if   0     <= code < 4096:   c0.append(code)
        elif 4096  <= code < 8192:   c1.append(code - 4096)
        elif 8192  <= code < 12288:  c2.append(code - 8192)
        elif 12288 <= code < 16384:  c2.append(code - 12288)
        elif 16384 <= code < 20480:  c1.append(code - 16384)
        elif 20480 <= code < 24576:  c2.append(code - 20480)
        elif 24576 <= code < 28672:  c2.append(code - 24576)

    if not c0:
        print("All frames were out of range — wrong codec offset or model not Orpheus")
        return None

    # Enforce strict 1:2:4 ratio — model occasionally emits extra codes in one band
    n = min(len(c0), len(c1) // 2, len(c2) // 4)
    c0, c1, c2 = c0[:n], c1[:2*n], c2[:4*n]

    print(f"Decoding {n} SNAC frames...")
    with torch.no_grad():
        waveform = snac_model.decode([
            torch.tensor(c0, dtype=torch.long).unsqueeze(0),
            torch.tensor(c1, dtype=torch.long).unsqueeze(0),
            torch.tensor(c2, dtype=torch.long).unsqueeze(0),
        ])
    return waveform.squeeze().cpu().numpy()


def text_to_speech(text: str, output_path: str = OUTPUT_WAV):
    codes = generate_audio_tokens(text, SPEAKER_NAME)
    if not codes:
        print("\n❌ No audio codes generated.")
        print("   Possible causes:")
        print("   1. GGUF was exported from a model NOT trained on audio (wrong Colab cells)")
        print("   2. Wrong SPEAKER_NAME — must match exactly what was used in Colab Cell 5")
        print("   3. CODEC_OFFSET mismatch — run debug_tokens() to investigate")
        return False

    audio = decode_audio(codes)
    if audio is None:
        return False

    sf.write(output_path, audio, 24000)
    print(f"\n✅ Saved: {output_path}  ({len(audio)/24000:.1f} seconds)")
    return True


def debug_tokens(text: str = "Hello."):
    """
    Run this if text_to_speech() produces nothing.
    Prints the first 30 raw token IDs so you can see what the model outputs.
    """
    prompt = build_orpheus_prompt(text, SPEAKER_NAME)
    prompt_ids = llm.tokenize(prompt.encode(), add_bos=True)
    print(f"\n=== DEBUG: first 30 generated token IDs ===")
    print(f"Prompt: {prompt[:120]}...\n")

    for i, token_id in enumerate(llm.generate(prompt_ids, temp=0.6)):
        decoded = llm.detokenize([token_id]).decode("utf-8", errors="replace")
        flag = " ← AUDIO" if token_id >= CODEC_OFFSET else ""
        print(f"  [{i:03d}] id={token_id:6d}  text={repr(decoded):20s}{flag}")
        if i >= 29:
            break
    print("=" * 44)
    print(f"\nIf you see NO ids >= {CODEC_OFFSET}, the model isn't generating audio tokens.")
    print("This means the Colab training used the wrong format — redo Colab cells 4-6")
    print("using the corrected cells in colab_cells_fixed.py\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        debug_tokens("Hello, testing.")
    else:
        text = "Hello. Good morning. My name is Aswini."
        text_to_speech(text)
