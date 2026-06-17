import json
import logging
import os
from types import SimpleNamespace
from typing import Any, AsyncGenerator, Dict, List, Optional

import aiohttp

from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.inworld.ai/llm/v1/chat/completions"
_DEFAULT_MODEL = os.getenv("INWORLD_LLM_MODEL", "inworld/inworld-llm-v1")


class InworldLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Inworld"
        self.model = model or _DEFAULT_MODEL
        self.api_key = api_key

        if not self.api_key:
            logger.warning("InworldLLM initialized without API key — streams will fail.")

    async def stream(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            yield {"type": "error", "content": "Missing Inworld API Key"}
            return

        headers = {
            "Authorization": f"Basic {self.api_key}",
            "Content-Type": "application/json",
        }

        history = self.get_safe_history(limit=10)

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": history,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.7,
            "max_tokens": 2048,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        logger.info(
            "🧠 [InworldLLM] model=%s messages=%d tools=%s",
            self.model,
            len(history),
            bool(tools),
        )

        timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)

        try:
            accumulated_text = ""
            full_reply = ""
            tool_calls_dict: Dict[int, Dict] = {}
            _last_usage_raw = None

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(_BASE_URL, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        err = await resp.text()
                        logger.error("❌ [InworldLLM] API error %d: %s", resp.status, err[:300])
                        yield {"type": "error", "content": f"Inworld API error {resp.status}: {err[:200]}"}
                        return

                    async for line in resp.content:
                        line = line.decode("utf-8").strip()
                        if not line or line == "data: [DONE]":
                            continue
                        if not line.startswith("data: "):
                            continue

                        try:
                            chunk = json.loads(line[6:])

                            if "error" in chunk:
                                logger.error("❌ [InworldLLM] mid-stream error: %s", chunk["error"])
                                yield {"type": "error", "content": str(chunk["error"])}
                                return

                            choices = chunk.get("choices", [])
                            if not choices:
                                if chunk.get("usage"):
                                    _last_usage_raw = chunk["usage"]
                                continue

                            delta = choices[0].get("delta", {})

                            # Text tokens
                            if delta.get("content"):
                                content = delta["content"]
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
                            if delta.get("tool_calls"):
                                for tc in delta["tool_calls"]:
                                    idx = tc.get("index", 0)
                                    if idx not in tool_calls_dict:
                                        tool_calls_dict[idx] = {
                                            "id": tc.get("id"),
                                            "type": "function",
                                            "function": {
                                                "name": tc.get("function", {}).get("name"),
                                                "arguments": tc.get("function", {}).get("arguments", ""),
                                            },
                                        }
                                    else:
                                        fn_args = tc.get("function", {}).get("arguments", "")
                                        if fn_args:
                                            tool_calls_dict[idx]["function"]["arguments"] += fn_args

                        except Exception as exc:
                            logger.warning("[InworldLLM] chunk parse error: %s | line=%r", exc, line[:100])

            if accumulated_text.strip():
                yield {"type": "sentence", "content": accumulated_text.strip()}

            formatted_tool_calls = []
            for i in sorted(tool_calls_dict):
                tc = tool_calls_dict[i]
                formatted_tool_calls.append(
                    SimpleNamespace(
                        id=tc["id"],
                        function=SimpleNamespace(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        ),
                    )
                )

            self.last_usage = {
                "prompt_tokens": _last_usage_raw.get("prompt_tokens") if _last_usage_raw else None,
                "completion_tokens": _last_usage_raw.get("completion_tokens") if _last_usage_raw else None,
            }

            yield {
                "type": "finished",
                "full_reply": full_reply,
                "tool_calls": formatted_tool_calls or None,
                "usage": self.last_usage,
            }

        except Exception as exc:
            logger.error("❌ [InworldLLM] stream error: %s", exc, exc_info=True)
            yield {"type": "error", "content": str(exc)}
