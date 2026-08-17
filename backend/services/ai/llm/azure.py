import asyncio
import logging
import os
import re as _re
import uuid as _uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from openai import AsyncAzureOpenAI

from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)


class AzureLLM(BaseLLM):
    """Azure OpenAI LLM — streaming, tool-calling, BaseLLM-compatible.

    Required env vars (or company settings):
        AZURE_OPENAI_ENDPOINT  — e.g. https://my-resource.openai.azure.com
        AZURE_OPENAI_API_VERSION — default: 2024-02-01
        AZURE_API_KEY (or AZURE_OPENAI_API_KEY)
    """

    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Azure"
        self.model = model or os.getenv("AZURE_OPENAI_MODEL", "gpt-4o")
        self.api_key = api_key or os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("AZURE_API_KEY")
        self.endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")

        if not self.api_key:
            logger.warning("AzureLLM: no API key — streams will fail.")
        if not self.endpoint:
            logger.warning("AzureLLM: AZURE_OPENAI_ENDPOINT not set — streams will fail.")

        self.client = (
            AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
            if self.api_key and self.endpoint
            else None
        )

    async def stream(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.client:
            yield {"type": "error", "content": "AzureLLM not configured (missing api_key or endpoint)"}
            return

        max_retries = 3
        current_tools = tools

        for attempt in range(max_retries):
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict: Dict[int, Any] = {}

                self.clean_interrupted_tool_calls()

                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=current_tools or None,
                    max_tokens=2048,
                    temperature=0.7,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                _last_usage_raw = None
                async for chunk in stream:
                    if not chunk.choices:
                        if getattr(chunk, "usage", None):
                            _last_usage_raw = chunk.usage
                        continue

                    delta = chunk.choices[0].delta

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

                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                self.last_usage = {
                    "prompt_tokens": getattr(_last_usage_raw, "prompt_tokens", None),
                    "completion_tokens": getattr(_last_usage_raw, "completion_tokens", None),
                } if _last_usage_raw else {}
                yield {
                    "type": "finished",
                    "full_reply": full_reply,
                    "tool_calls": [tool_calls_dict[i] for i in sorted(tool_calls_dict)] if tool_calls_dict else None,
                    "usage": self.last_usage,
                }
                return

            except Exception as exc:
                logger.error("❌ [AzureLLM] Stream error (attempt %s): %s", attempt + 1, exc)
                err_str = str(exc)

                if "429" in err_str and attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    continue

                yield {"type": "error", "content": err_str}
                return
