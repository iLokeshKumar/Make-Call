import asyncio
import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from groq import AsyncGroq

from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)


class GroqLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Groq"

        self.model = model or "llama-3.3-70b-versatile"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("GroqLLM initialized without an API key! Streams will fail.")

        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None

    async def stream(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.client:
            raise ValueError("Groq Client is not initialized due to missing API key")

        max_retries = 3
        for attempt in range(max_retries):
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict: Dict[int, Any] = {}

                # Clean up any unfulfilled tool calls from previous (interrupted) turns
                self.clean_interrupted_tool_calls()

                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=tools,
                    max_completion_tokens=2048,
                    temperature=0.7,
                    stream=True,
                )

                async for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # Content
                    content = getattr(delta, "content", None)
                    if content:
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

                    # Tool calls — key by index (Groq streaming deltas only carry id/name on the first chunk; subsequent chunks carry argument fragments and share the same index).
                    tc_list = getattr(delta, "tool_calls", None)
                    if tc_list:
                        for tc in tc_list:
                            idx = getattr(tc, "index", None)
                            if idx is None:
                                continue

                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = tc
                            else:
                                existing_fn = getattr(tool_calls_dict[idx], "function", None)
                                new_fn = getattr(tc, "function", None)
                                if existing_fn and new_fn:
                                    new_args = getattr(new_fn, "arguments", "") or ""
                                    if new_args:
                                        existing_fn.arguments = (existing_fn.arguments or "") + new_args

                # Final remaining chunk
                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                # End of stream metadata
                yield {
                    "type": "finished",
                    "full_reply": full_reply,
                    "tool_calls": [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())] if tool_calls_dict else None,
                }
                return

            except Exception as exc:
                logger.error("❌ [GroqLLM] Stream Error: %s", exc)
                if "429" in str(exc) and attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1, 2, 4
                    logger.warning(
                        "⚠️ [GroqLLM] Rate limited. Waiting %ss before retry %s...",
                        wait,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue

                yield {"type": "error", "content": str(exc)}
                return
