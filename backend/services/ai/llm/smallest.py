import asyncio
import logging
import os
from typing import Optional, List, Dict, Any, AsyncGenerator

from openai import AsyncOpenAI
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)


class SmallestLLM(BaseLLM):

    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Smallest"
        self.model = model or "electron"
        self.api_key = api_key or os.getenv("SMALLEST_API_KEY")

        if not self.api_key:
            logger.warning("SmallestLLM initialized without an API key! Streams will fail.")

        self.client = (
            AsyncOpenAI(
                api_key=self.api_key,
                base_url="https://api.smallest.ai/waves/v1",
            )
            if self.api_key
            else None
        )

    async def stream(
        self, tools: Optional[List[Dict[str, Any]]] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.client:
            yield {"type": "error", "content": "SmallestLLM not configured (missing api_key)"}
            return

        max_retries = 3
        backoff = [0, 2, 8]

        for attempt in range(max_retries):
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict: Dict[int, Any] = {}

                self.clean_interrupted_tool_calls()

                kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "messages": self.messages,
                    "max_tokens": 2048,
                    "temperature": 0.7,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                }
                if tools:
                    kwargs["tools"] = tools
                stream = await self.client.chat.completions.create(**kwargs)

                _last_usage_raw = None
                async for chunk in stream:
                    if not chunk.choices:
                        if getattr(chunk, "usage", None):
                            _last_usage_raw = chunk.usage
                        continue
                    delta = chunk.choices[0].delta

                    # Content tokens
                    content = getattr(delta, "content", None)
                    if content:
                        accumulated_text += content
                        full_reply += content
                        yield {"type": "token", "content": content}

                        parts = SENTENCE_SPLIT_REGEX.split(accumulated_text)
                        if len(parts) > 1:
                            sentence = parts[0] + parts[1]
                            accumulated_text = accumulated_text[len(sentence):]
                            if sentence.strip():
                                yield {"type": "sentence", "content": sentence.strip()}

                    # Tool calls
                    tc_list = getattr(delta, "tool_calls", None)
                    if tc_list:
                        for tc in tc_list:
                            idx = getattr(tc, "index", 0)
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = tc
                            else:
                                fn = getattr(tool_calls_dict[idx], "function", None)
                                new_fn = getattr(tc, "function", None)
                                if fn and new_fn:
                                    new_args = getattr(new_fn, "arguments", "") or ""
                                    if new_args:
                                        fn.arguments = (fn.arguments or "") + new_args

                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                self.last_usage = {
                    "prompt_tokens": getattr(_last_usage_raw, "prompt_tokens", None),
                    "completion_tokens": getattr(_last_usage_raw, "completion_tokens", None),
                } if _last_usage_raw else {}
                yield {
                    "type": "finished",
                    "full_reply": full_reply,
                    "tool_calls": (
                        [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())]
                        if tool_calls_dict
                        else None
                    ),
                    "usage": self.last_usage,
                }
                return

            except Exception as exc:
                err = str(exc)
                is_rate_limit = "429" in err
                if is_rate_limit and attempt < max_retries - 1:
                    wait = backoff[attempt + 1]
                    logger.warning("⚠️ [SmallestLLM] Rate limited. Waiting %ss (attempt %s)...", wait, attempt + 1)
                    await asyncio.sleep(wait)
                    continue

                logger.error("❌ [SmallestLLM] Stream error (attempt %s): %s", attempt + 1, exc)
                yield {"type": "error", "content": err}
                return
