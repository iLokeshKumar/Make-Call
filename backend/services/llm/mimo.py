import json
import logging
import aiohttp
import asyncio
from types import SimpleNamespace
from typing import Optional, List, Dict, Any, AsyncGenerator
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)


class MimoLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Mimo"
        self.model = model or "mimo-v2-pro"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("MimoLLM initialized without an API key! Streams will fail.")

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            yield {"type": "error", "content": "Missing Mimo API Key in user settings"}
            return

        url = "https://api.xiaomimimo.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        def sanitize_obj(obj):
            if isinstance(obj, list):
                return [sanitize_obj(i) for i in obj]
            if isinstance(obj, dict):
                return {k: sanitize_obj(v) for k, v in obj.items()}
            if hasattr(obj, "__dict__"):
                return sanitize_obj(obj.__dict__)
            if hasattr(obj, "id") and hasattr(obj, "function"):
                return {
                    "id": obj.id,
                    "type": "function",
                    "function": {
                        "name": obj.function.name,
                        "arguments": obj.function.arguments,
                    },
                }
            return str(obj)

        final_history = self.get_safe_history(limit=10)
        # Strip reasoning_content Mimo sometimes injects into prior assistant turns
        for msg in final_history:
            if msg.get("role") == "assistant":
                msg.pop("reasoning_content", None)
        sanitized_messages = sanitize_obj(final_history)

        payload = {
            "model": self.model,
            "messages": sanitized_messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
        }
        if tools:
            payload["tools"] = sanitize_obj(tools)
            payload["tool_choice"] = "auto"

        logger.info(f"🧠 [MimoLLM] Sending {len(sanitized_messages)} messages | Model: {self.model}")

        max_retries = 2
        retry_count = 0
        timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)

        while retry_count <= max_retries:
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict = {}

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status == 429:
                            retry_count += 1
                            if retry_count <= max_retries:
                                await asyncio.sleep(retry_count * 2)
                                continue
                            yield {"type": "error", "content": "Mimo API Rate Limited (429)"}
                            return

                        if resp.status != 200:
                            error_text = await resp.text()
                            logger.error(f"❌ [MimoLLM] API Error {resp.status}: {error_text}")
                            yield {"type": "error", "content": f"Mimo API Error {resp.status}"}
                            return

                        async for line in resp.content:
                            line = line.decode("utf-8").strip()
                            if not line or line == "data: [DONE]":
                                continue
                            if line.startswith("data: "):
                                try:
                                    chunk = json.loads(line[6:])
                                    if "error" in chunk:
                                        logger.error(f"❌ [MimoLLM] Stream error: {chunk['error']}")
                                        yield {"type": "error", "content": "Mimo stream error"}
                                        return

                                    choices = chunk.get("choices", [])
                                    if not choices:
                                        continue
                                    delta = choices[0].get("delta", {})

                                    # Skip reasoning_content tokens (internal chain-of-thought)
                                    if "reasoning_content" in delta:
                                        continue

                                    if "content" in delta and delta["content"]:
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

                                    if "tool_calls" in delta:
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
                                                if "function" in tc and "arguments" in tc["function"]:
                                                    tool_calls_dict[idx]["function"]["arguments"] += tc["function"]["arguments"]
                                except Exception as e:
                                    logger.warning(f"⚠️ [MimoLLM] Chunk parse error: {e}")

                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                formatted_tool_calls = []
                for i in sorted(tool_calls_dict.keys()):
                    tc = tool_calls_dict[i]
                    formatted_tool_calls.append(SimpleNamespace(
                        id=tc["id"],
                        function=SimpleNamespace(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"],
                        ),
                    ))

                yield {
                    "type": "finished",
                    "full_reply": full_reply,
                    "tool_calls": formatted_tool_calls if formatted_tool_calls else None,
                }
                return

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    logger.warning(f"⚠️ [MimoLLM] Connection error: {e}. Retrying...")
                    await asyncio.sleep(retry_count * 2)
                    continue
                logger.error(f"❌ [MimoLLM] Connection failed after retries: {e}")
                yield {"type": "error", "content": f"Connection failure: {str(e)}"}
                return
            except Exception as e:
                logger.error(f"❌ [MimoLLM] Unexpected error: {e}")
                yield {"type": "error", "content": str(e)}
                return
