import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from .base import BaseLLM, SENTENCE_SPLIT_REGEX
from .airllm_provider import format_prompt, generate_sync

logger = logging.getLogger(__name__)


class AirLLMLLM(BaseLLM):
    """
    Local HuggingFace LLM via AirLLM (layer-wise inference, consumer GPU/CPU).
    Configured entirely via env vars — api_key/model params are ignored.

    Env vars:
        AIRLLM_MODEL           HuggingFace model ID (required)
        AIRLLM_COMPRESSION     4bit | 8bit | (empty=none)  default: 4bit
        AIRLLM_MAX_NEW_TOKENS  default: 512
        AIRLLM_MAX_SEQ_LEN     default: 256
        AIRLLM_HF_TOKEN        for gated models (optional)
    """

    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "AirLLM"

    async def stream(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if tools:
            logger.warning("[AirLLM] Tool calls not supported — proceeding without tools")

        self.clean_interrupted_tool_calls()

        loop = asyncio.get_event_loop()
        try:
            prompt = format_prompt(self.messages)
            output = await loop.run_in_executor(None, generate_sync, prompt)
        except Exception as exc:
            logger.error("[AirLLM] Generation error: %s", exc)
            yield {"type": "error", "content": str(exc)}
            return

        # Fake streaming: yield word-by-word, detect sentence boundaries for TTS
        accumulated = ""
        for word in output.split():
            token = word + " "
            accumulated += token
            yield {"type": "token", "content": token}

            parts = SENTENCE_SPLIT_REGEX.split(accumulated)
            if len(parts) > 1:
                sentence = parts[0] + parts[1]
                accumulated = accumulated[len(sentence):]
                if sentence.strip():
                    yield {"type": "sentence", "content": sentence.strip()}

        if accumulated.strip():
            yield {"type": "sentence", "content": accumulated.strip()}

        yield {"type": "finished", "full_reply": output, "tool_calls": None}
