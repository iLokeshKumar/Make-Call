from __future__ import annotations

import json
import logging
import re
import aiohttp
import asyncio
from types import SimpleNamespace
from typing import Optional, List, Dict, Any, AsyncGenerator

from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)

_API_URL = "https://api.sarvam.ai/v1/chat/completions"

# JSON leakage patterns
_JSON_TOKEN_PATTERNS = (
    '"arguments":', '"name":', '"id":', '": "',
    '"email":', '"phone":', '"lead_id":', '"status":',
    '"company":', '"result":', '"function":', '"tool_call":',
    '"value":', '"type":', '"data":', '"content":',
    '"message":', '"role":', '"action":', '"parameters":',
)
_JSON_KV_RE = re.compile(r'"[a-z_]{2,24}"\s*:\s*["{0-9\[Ttf]')


class SarvamLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Sarvam"
        self.model = model or "sarvam-105b"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("SarvamLLM initialised without an API key. Streams will fail.")

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        headers = {
            "api-subscription-key": self.api_key,
            "Content-Type": "application/json",
        }

        # Use tool-safe history (avoids orphan tool messages on barge-in)
        final_history = self.get_safe_history(limit=8)

        # If the history contains tool messages or assistant tool_calls but
        # the caller did not supply a `tools` list, strip those entries to
        # avoid API errors like: "Tool messages found but no tools provided.".
        has_tool_msgs = any(
            m.get("role") == "tool" or (
                m.get("role") == "assistant" and m.get("tool_calls")
            )
            for m in final_history
        )
        if has_tool_msgs and not tools:
            logger.warning(
                "[SarvamLLM] Tool-related history present but no tools provided; stripping tool messages to avoid API errors."
            )
            cleaned: list[dict] = []
            for m in final_history:
                if m.get("role") == "tool":
                    continue
                if m.get("role") == "assistant" and m.get("tool_calls"):
                    m = dict(m)
                    m.pop("tool_calls", None)
                    if not m.get("content"):
                        # Skip empty assistant messages left over after stripping
                        continue
                cleaned.append(m)
            final_history = cleaned

        _NO_TOOL_MODELS = {"sarvam-m", "sarvam-2b"}
        supports_tools = self.model not in _NO_TOOL_MODELS

        # Reinforce no-JSON-in-speech instruction (always) or prompt-based tool substitution when the model can't use structured tool calls.
        system_msgs = [m for m in final_history if m["role"] == "system"]
        if system_msgs:
            base_addition = (
                "\n\nCRITICAL: Never output JSON, tool-call syntax, or markdown in your spoken reply. "
            )
            if supports_tools:
                base_addition += "Use the provided tool-calling interface for all structured actions."
            else:
                base_addition += (
                    "You cannot use tool calls. Instead speak naturally and confirm any actions verbally. "
                    "Example: say 'I've noted your details' rather than trying to call a function."
                )
            system_msgs[0]["content"] += base_addition

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": final_history,
            "stream": True,
            "stream_options": {"include_usage": True},
            "temperature": 0.7,
            "max_tokens": 2048,
        }

        if tools and supports_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        elif tools and not supports_tools:
            logger.warning(
                "[SarvamLLM] model=%s does not support tool calling — proceeding without tools.",
                self.model,
            )

        logger.info(
            "🧠 [SarvamLLM] model=%s messages=%d tools=%s",
            self.model, len(final_history), bool(tools),
        )

        max_retries = 2
        retry_count = 0
        timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)

        while retry_count <= max_retries:
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict: Dict[int, Dict] = {}
                error_occurred = False
                _json_depth = 0
                _kv_window = ""
                _last_usage_raw = None

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(_API_URL, headers=headers, json=payload) as resp:
                        if resp.status == 429:
                            retry_count += 1
                            if retry_count <= max_retries:
                                wait = retry_count * 2
                                logger.warning("[SarvamLLM] Rate limited (429). Retrying in %ds…", wait)
                                await asyncio.sleep(wait)
                                continue
                            logger.error("[SarvamLLM] Rate limit exceeded after retries.")
                            yield {"type": "error", "content": "Sarvam API rate limited"}
                            return

                        if resp.status != 200:
                            body = await resp.text()
                            logger.error("[SarvamLLM] API error %d: %s", resp.status, body[:200])
                            yield {"type": "error", "content": f"Sarvam API error {resp.status}"}
                            return

                        async for raw_line in resp.content:
                            line = raw_line.decode("utf-8").strip()
                            if not line or line == "data: [DONE]":
                                continue

                            if not line.startswith("data: "):
                                continue

                            try:
                                chunk = json.loads(line[6:])
                            except Exception:
                                continue

                            if "error" in chunk:
                                logger.error("[SarvamLLM] Mid-stream error: %s", chunk["error"])
                                if not full_reply and retry_count < max_retries:
                                    error_occurred = True
                                    break
                                yield {"type": "error", "content": "Sarvam mid-stream error"}
                                error_occurred = True
                                break

                            choices = chunk.get("choices", [])
                            if not choices:
                                if chunk.get("usage"):
                                    _last_usage_raw = chunk["usage"]
                                continue

                            delta = choices[0].get("delta", {})

                            # Content
                            if delta.get("content"):
                                content = delta["content"]

                                # brace-depth JSON block suppression
                                opens = content.count("{")
                                closes = content.count("}")
                                was_in_json = _json_depth > 0
                                _json_depth = max(0, _json_depth + opens - closes)
                                if was_in_json or opens > 0:
                                    logger.warning(
                                        "🚫 [SarvamLLM] JSON block suppressed: %r", content[:40]
                                    )
                                    continue

                                # known JSON key patterns
                                if any(p in content for p in _JSON_TOKEN_PATTERNS):
                                    logger.warning(
                                        "🚫 [SarvamLLM] JSON token pattern suppressed: %r", content[:40]
                                    )
                                    continue

                                # sliding-window key:value detection
                                _kv_window = (_kv_window + content)[-80:]
                                if _JSON_KV_RE.search(_kv_window):
                                    logger.warning(
                                        "🚫 [SarvamLLM] JSON kv window suppressed: %r", _kv_window[-40:]
                                    )
                                    _kv_window = ""
                                    continue

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
                                        args_delta = tc.get("function", {}).get("arguments", "")
                                        tool_calls_dict[idx]["function"]["arguments"] += args_delta

                if error_occurred:
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.warning("[SarvamLLM] Retrying after mid-stream error (attempt %d)…", retry_count)
                        await asyncio.sleep(retry_count)
                        continue
                    return

                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                formatted_tool_calls = []
                for i in sorted(tool_calls_dict.keys()):
                    tc = tool_calls_dict[i]
                    raw_args = tc["function"].get("arguments") or "{}"

                    try:
                        json.loads(raw_args)
                        clean_args = raw_args
                    except json.JSONDecodeError:

                        m = re.search(r'\{.*?\}', raw_args, re.DOTALL)
                        try:
                            clean_args = json.dumps(json.loads(m.group(0))) if m else "{}"
                        except Exception:
                            clean_args = "{}"
                        logger.warning(
                            "[SarvamLLM] Malformed tool-call arguments for %s — "
                            "raw: %r  cleaned: %r",
                            tc["function"].get("name"), raw_args[:120], clean_args,
                        )
                    formatted_tool_calls.append(
                        SimpleNamespace(
                            id=tc["id"],
                            function=SimpleNamespace(
                                name=tc["function"]["name"],
                                arguments=clean_args,
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
                return

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                retry_count += 1
                if retry_count <= max_retries:
                    logger.warning("[SarvamLLM] Connection error: %s. Retrying in %ds…", exc, retry_count * 2)
                    await asyncio.sleep(retry_count * 2)
                    continue
                logger.error("[SarvamLLM] Failed after %d retries: %s", max_retries, exc)
                yield {"type": "error", "content": str(exc)}
                return
            except Exception as exc:
                logger.error("[SarvamLLM] Unexpected error: %s", exc, exc_info=True)
                yield {"type": "error", "content": str(exc)}
                return
