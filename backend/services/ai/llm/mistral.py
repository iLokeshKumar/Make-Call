import json
import logging
import asyncio

from mistralai.client import Mistral
from typing import Optional, List, Dict, Any, AsyncGenerator
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

# Provider-agnostic counters live in services.observability so /health and
# tests can read them without dragging the full LLM SDK chain.
from services.observability import (
    record_rate_limit_hit as _record_rate_limit_hit,
    get_rate_limit_hits_last_15min,  # noqa: F401  (re-exported for back-compat)
)

logger = logging.getLogger(__name__)

class MistralLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Mistral"
        self.model = model or "mistral-large-latest"
        self.api_key = api_key
        
        if not self.api_key:
            logger.warning("MistralLLM initialized without an API key! Streams will fail.")
            
        self.client = Mistral(api_key=self.api_key) if self.api_key else None

    async def stream(self, tools: Optional[List[Dict[str, Any]]] = None) -> AsyncGenerator[Dict[str, Any], None]:
        max_retries = 4
        # Exponential backoff ladder: 2s, 8s, 30s. Free tier = 1 req/sec, so a
        # short retry hits the same limited window. Long ladder = better odds
        # the bucket refilled by the time we retry.
        backoff_seconds = [0, 2, 8, 30]
        for attempt in range(max_retries):
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict = {}

                if not self.client:
                    raise ValueError("Mistral Client is not initialized due to missing API key")

                # Clean up any unfulfilled tool calls from previous (interrupted) turns
                self.clean_interrupted_tool_calls()
                final_history = self.get_safe_history(limit=10)

                stream = await self.client.chat.stream_async(
                    model=self.model,
                    messages=final_history,
                    tools=tools,
                    max_tokens=2048,
                    temperature=0.7
                )

                async for chunk in stream:
                    delta = chunk.data.choices[0].delta
                
                    # 1. Content
                    if delta.content:
                        content = delta.content
                        accumulated_text += content
                        full_reply += content
                        yield {"type": "token", "content": content}

                        # Sentence boundary detection
                        parts = SENTENCE_SPLIT_REGEX.split(accumulated_text)
                        if len(parts) > 1:
                            sentence = parts[0] + parts[1]
                            accumulated_text = accumulated_text[len(sentence):]
                            if sentence.strip():
                                yield {"type": "sentence", "content": sentence.strip()}

                    # 2. Tool Calls
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = tc
                            else:
                                tool_calls_dict[idx].function.arguments += tc.function.arguments

                # Final remaining chunk
                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                    # End of stream metadata
                yield {
                    "type": "finished", 
                    "full_reply": full_reply, 
                    "tool_calls": [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())] if tool_calls_dict else None
                }
                return # Success, exit loop

            except Exception as e:
                is_rate_limit = "429" in str(e)
                if is_rate_limit:
                    _record_rate_limit_hit()
                if is_rate_limit and attempt < max_retries - 1:
                    wait = backoff_seconds[attempt + 1]
                    logger.warning(f"⚠️ [MistralLLM] Rate limited. Waiting {wait}s before retry {attempt+1}...")
                    await asyncio.sleep(wait)
                    continue
                logger.error(f"❌ [MistralLLM] Stream Error: {e}")
                yield {"type": "error", "content": str(e)}
                return
