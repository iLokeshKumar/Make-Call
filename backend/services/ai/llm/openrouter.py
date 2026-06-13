import json
import logging
import os
import time
import aiohttp
import asyncio
from types import SimpleNamespace
from typing import Optional, List, Dict, Any, AsyncGenerator
from .base import BaseLLM, SENTENCE_SPLIT_REGEX
logger = logging.getLogger(__name__)

# Free / experimental OpenRouter models often break streaming tool calls (502 mid-stream).
_UNRELIABLE_TOOL_MODEL_MARKERS = (":free", "gpt-oss")
_TOOL_FALLBACK_MODEL = os.getenv("OPENROUTER_TOOL_FALLBACK_MODEL", "openai/gpt-4o-mini")
_DEBUG_LOG_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "debug-c56e15.log")


def _agent_debug_log(location: str, message: str, data: dict | None = None, hypothesis_id: str = "", run_id: str = "pre-fix"):
    # #region agent log
    try:
        entry = {
            "sessionId": "c56e15",
            "timestamp": int(time.time() * 1000),
            "location": location,
            "message": message,
            "data": data or {},
            "hypothesisId": hypothesis_id,
            "runId": run_id,
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    # #endregion


def _is_unreliable_for_tools(model: str) -> bool:
    lower = (model or "").lower()
    return any(marker in lower for marker in _UNRELIABLE_TOOL_MODEL_MARKERS)

class OpenRouterLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "OpenRouter"
        self.model = model
        self.api_key = api_key
        
        if not self.api_key:
            logger.warning("OpenRouterLLM initialized without an API key! Streams will fail.")

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.api_key:
            yield {"type": "error", "content": "Missing OpenRouter API Key in user settings"}
            return
            
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://rio-voice.local",
            "X-Title": "Rio Voice Agent"
        }
        
        # Deep-sanitize messages to ensure JSON serialization
        def sanitize_obj(obj):
            if isinstance(obj, list):
                return [sanitize_obj(i) for i in obj]
            if isinstance(obj, dict):
                return {k: sanitize_obj(v) for k, v in obj.items()}
            return str(obj)

        final_history = self.get_safe_history(limit=10)
        sanitized_messages = sanitize_obj(final_history)

        effective_model = self.model
        if tools and _is_unreliable_for_tools(self.model):
            effective_model = _TOOL_FALLBACK_MODEL
            logger.warning(
                "⚠️ [OpenRouterLLM] Model %r is unreliable for tool calling; "
                "using fallback %r",
                self.model,
                effective_model,
            )
            _agent_debug_log(
                "openrouter.py:stream",
                "tool_model_fallback",
                {"configured": self.model, "effective": effective_model},
                hypothesis_id="H1",
            )

        # Prepare payload
        payload = {
            "model": effective_model,
            "messages": sanitized_messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048
        }
        
        # Only enable reasoning for specific models known to support it via this field
        # Most models will throw a 500 if they don't recognize the 'reasoning' block
        if any(m in self.model.lower() for m in ["trinity", "deepseek-r1"]):
            payload["reasoning"] = {"enabled": True}
        
        if tools:
            payload["tools"] = sanitize_obj(tools)
            payload["tool_choice"] = "auto"

        logger.info(
            "🧠 [OpenRouterLLM] Sending Payload. Messages: %s | Tools: %s | Model: %s",
            len(sanitized_messages),
            bool(tools),
            effective_model,
        )
        _agent_debug_log(
            "openrouter.py:stream",
            "request_start",
            {"model": effective_model, "tools": bool(tools), "message_count": len(sanitized_messages)},
            hypothesis_id="H1",
        )
        logger.debug(f"📡 [OpenRouterLLM] Payload: {json.dumps(payload, indent=2)[:500]}...")

        timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
        
        try:
            accumulated_text = ""
            full_reply = ""
            tool_calls_dict = {}
            reasoning_details = ""

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        logger.error(f"❌ [OpenRouterLLM] API Error {resp.status}: {error_text}")
                        yield {"type": "error", "content": f"OpenRouter API Error {resp.status}"}
                        return

                    async for line in resp.content:
                        line = line.decode('utf-8').strip()
                        if not line or line == "data: [DONE]":
                            continue
                        
                        if line.startswith("data: "):
                            try:
                                chunk = json.loads(line[6:])
                                
                                if "error" in chunk:
                                    err = chunk['error']
                                    logger.error(f"❌ [OpenRouterLLM] Mid-stream Error: {err}")
                                    _agent_debug_log(
                                        "openrouter.py:stream",
                                        "mid_stream_error",
                                        {"error": str(err)[:500], "model": effective_model},
                                        hypothesis_id="H1",
                                    )
                                    yield {"type": "error", "content": "OpenRouter server error mid-stream"}
                                    return

                                choices = chunk.get('choices', [])
                                if not choices:
                                    continue

                                delta = choices[0].get('delta', {})
                                
                                # 1. Reasoning Tokens (Do not speak these, just accumulate)
                                if 'reasoning_details' in delta and delta['reasoning_details']:
                                    rd = delta['reasoning_details']
                                    if isinstance(rd, list):
                                        for item in rd:
                                            if isinstance(item, dict) and "text" in item:
                                                reasoning_details += item["text"]
                                            elif isinstance(item, str):
                                                reasoning_details += item
                                    elif isinstance(rd, str):
                                        reasoning_details += rd
                                    continue # Skip yielding to speech engine
                                    
                                if 'reasoning' in delta and delta['reasoning']:
                                    # Fallback if the API uses 'reasoning' delta stream instead of reasoning_details string
                                    r = delta['reasoning']
                                    if isinstance(r, str):
                                        reasoning_details += r
                                    continue

                                # 2. Spoken Content
                                if 'content' in delta and delta['content']:
                                    content = delta['content']
                                    
                                    # Suppress JSON / tool-call syntax leaking into spoken tokens
                                    _speech_leak_markers = (
                                        '"arguments":', '{"name":', '"name":', '"id":', '": "',
                                        "to=functions.", "to=tool_calls.", "[Assistant calls",
                                    )
                                    if any(p in content for p in _speech_leak_markers):
                                        logger.warning(
                                            "🚫 [OpenRouterLLM] Filtered tool/JSON leakage from speech: %r",
                                            content[:40],
                                        )
                                        _agent_debug_log(
                                            "openrouter.py:stream",
                                            "speech_leak_filtered",
                                            {"snippet": content[:80]},
                                            hypothesis_id="H2",
                                        )
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

                                # 3. Tool Calls
                                if 'tool_calls' in delta:
                                    for tc in delta['tool_calls']:
                                        idx = tc.get('index', 0)
                                        if idx not in tool_calls_dict:
                                            tool_calls_dict[idx] = {
                                                "id": tc.get("id"),
                                                "type": "function",
                                                "function": {
                                                    "name": tc.get("function", {}).get("name"),
                                                    "arguments": tc.get("function", {}).get("arguments", "")
                                                }
                                            }
                                        else:
                                            if "function" in tc and "arguments" in tc["function"]:
                                                tool_calls_dict[idx]["function"]["arguments"] += tc["function"]["arguments"]

                            except Exception as e:
                                logger.warning(f"⚠️ [OpenRouterLLM] Chunk Parse Error: {e} | Line: {line}")

            if accumulated_text.strip():
                yield {"type": "sentence", "content": accumulated_text.strip()}

            formatted_tool_calls = []
            if tool_calls_dict:
                for i in sorted(tool_calls_dict.keys()):
                    tc = tool_calls_dict[i]
                    obj = SimpleNamespace(
                        id=tc["id"],
                        function=SimpleNamespace(
                            name=tc["function"]["name"],
                            arguments=tc["function"]["arguments"]
                        )
                    )
                    formatted_tool_calls.append(obj)

            finish_obj = {
                "type": "finished", 
                "full_reply": full_reply, 
                "tool_calls": formatted_tool_calls if formatted_tool_calls else None
            }
            
            if reasoning_details:
                finish_obj["reasoning_details"] = reasoning_details
                logger.debug(f"🧠 [OpenRouterLLM] Captured {len(reasoning_details)} characters of reasoning details.")

            _agent_debug_log(
                "openrouter.py:stream",
                "stream_finished",
                {
                    "model": effective_model,
                    "tool_call_count": len(formatted_tool_calls),
                    "reply_len": len(full_reply),
                },
                hypothesis_id="H1",
            )
            yield finish_obj

        except Exception as e:
            logger.error(f"❌ [OpenRouterLLM] Stream Error: {e}")
            yield {"type": "error", "content": str(e)}
