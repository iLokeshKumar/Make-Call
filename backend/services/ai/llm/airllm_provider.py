"""
Shared AirLLM singleton + generation helpers.
Used by both AirLLMLLM (voice pipeline) and AirLLMChatModel (LangChain agents).
"""

import logging
import os
import threading
import sys
from types import ModuleType

logger = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _install_bettertransformer_compat_shim() -> None:
    """Make AirLLM use its native SDPA fallback on modern Optimum releases."""
    mock_module = ModuleType("optimum.bettertransformer")

    class UnsupportedBetterTransformer:
        @staticmethod
        def transform(model, *args, **kwargs):
            # AirLLM catches ValueError and retries with attn_implementation="sdpa".
            raise ValueError("Legacy Optimum BetterTransformer is disabled; use native SDPA")

    mock_module.BetterTransformer = UnsupportedBetterTransformer
    sys.modules["optimum.bettertransformer"] = mock_module


def get_airllm_singleton():
    global _model
    if _model is None:
        with _lock:
            if _model is None:
                model_path = os.environ.get("AIRLLM_MODEL")
                if not model_path:
                    raise ValueError("AIRLLM_MODEL env var is required to use AirLLM provider")
                
                compression = os.getenv("AIRLLM_COMPRESSION", "4bit") or None
                hf_token = os.getenv("AIRLLM_HF_TOKEN")
                kwargs = {}
                if compression:
                    kwargs["compression"] = compression
                if hf_token:
                    kwargs["hf_token"] = hf_token
                
                logger.info("[AirLLM] Loading model %s (compression=%s) ...", model_path, compression)
                
                # AirLLM 2.11 imports the removed Optimum BetterTransformer API.
                # Its own ValueError fallback already creates the model with
                # Transformers' native SDPA implementation.
                _install_bettertransformer_compat_shim()

                from airllm import AutoModel
                _model = AutoModel.from_pretrained(model_path, **kwargs)
                logger.info("[AirLLM] Model ready.")
    return _model

# Keep your format_prompt and generate_sync functions exactly as they are...



# def get_airllm_singleton():
#     global _model
#     if _model is None:
#         with _lock:
#             if _model is None:
#                 model_path = os.environ.get("AIRLLM_MODEL")
#                 if not model_path:
#                     raise ValueError("AIRLLM_MODEL env var is required to use AirLLM provider")
#                 compression = os.getenv("AIRLLM_COMPRESSION", "4bit") or None
#                 hf_token = os.getenv("AIRLLM_HF_TOKEN")
#                 kwargs = {}
#                 if compression:
#                     kwargs["compression"] = compression
#                 if hf_token:
#                     kwargs["hf_token"] = hf_token
#                 logger.info("[AirLLM] Loading model %s (compression=%s) ...", model_path, compression)
#                 from airllm import AutoModel
#                 _model = AutoModel.from_pretrained(model_path, **kwargs)
#                 logger.info("[AirLLM] Model ready.")
#     return _model


def format_prompt(messages: list) -> str:
    """Convert OpenAI-style message list → prompt string via tokenizer chat template."""
    model = get_airllm_singleton()
    tok = model.tokenizer
    if hasattr(tok, "apply_chat_template"):
        try:
            return tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            # The hand-rolled fallback below uses a generic role-marker
            # format that may not match what this specific model was
            # trained on - log loudly so we don't silently degrade quality.
            logger.exception(
                "[AirLLM] tokenizer.apply_chat_template failed; "
                "falling back to generic <|role|> markers - output quality "
                "may suffer until the tokenizer is fixed."
            )
    # Fallback for tokenizers without apply_chat_template
    parts = []
    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"<|system|>\n{content}")
        elif role == "user":
            parts.append(f"<|user|>\n{content}")
        elif role == "assistant":
            parts.append(f"<|assistant|>\n{content}")
    parts.append("<|assistant|>")
    return "\n".join(parts)


def generate_sync(prompt: str) -> str:
    """Blocking generation — intended to be called from a thread executor."""
    model = get_airllm_singleton()
    max_seq = int(os.getenv("AIRLLM_MAX_SEQ_LEN", "256"))
    max_new = int(os.getenv("AIRLLM_MAX_NEW_TOKENS", "512"))

    tokens = model.tokenizer(
        [prompt],
        return_tensors="pt",
        return_attention_mask=False,
        truncation=True,
        max_length=max_seq,
        padding=False,
    )

    # Move to GPU if CUDA is available; fall back to CPU otherwise.
    # We check torch.cuda explicitly instead of catching a blanket Exception
    # so a real CUDA failure (OOM, driver mismatch) surfaces instead of
    # silently degrading to slow CPU inference.
    try:
        import torch  # local import: torch is heavy
        if torch.cuda.is_available():
            input_ids = tokens["input_ids"].cuda()
        else:
            input_ids = tokens["input_ids"]
    except ImportError:
        # torch should always be present (it's an airllm dep), but if it
        # isn't we cannot generate anything at all.
        raise

    out = model.generate(
        input_ids,
        max_new_tokens=max_new,
        use_cache=True,
        return_dict_in_generate=True,
    )

    full = model.tokenizer.decode(out.sequences[0], skip_special_tokens=True)
    # Strip the prompt prefix that HuggingFace echoes in the output
    if full.startswith(prompt):
        full = full[len(prompt):]
    return full.strip()
