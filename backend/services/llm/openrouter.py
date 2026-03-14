import json
import logging
import aiohttp
import asyncio
from types import SimpleNamespace
from typing import Optional, List, Dict, Any, AsyncGenerator
from .base import BaseLLM, SENTENCE_SPLIT_REGEX
from utils.config import OPENROUTER_API_KEY, OPENROUTER_MODEL

logger = logging.getLogger(__name__)

class OpenRouterLLM(BaseLLM):
    def __init__(self, system_prompt: str):
        super().__init__(system_prompt)
        self.provider = "OpenRouter"
        self.model = OPENROUTER_MODEL

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
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
            if hasattr(obj, "__dict__"):
                return sanitize_obj(obj.__dict__)
            if hasattr(obj, "id") and hasattr(obj, "function"):
                return {
                    "id": obj.id,
                    "type": "function",
                    "function": {
                        "name": obj.function.name,
                        "arguments": obj.function.arguments
                    }
                }
            return str(obj)

        final_history = self.get_safe_history(limit=10)
        sanitized_messages = sanitize_obj(final_history)

        # Prepare payload with reasoning tokens enabled
        payload = {
            "model": self.model,
            "messages": sanitized_messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048,
            "reasoning": {"enabled": True}  # Vital for Trinity/DeepSeek models
        }
        
        if tools:
            payload["tools"] = sanitize_obj(tools)
            payload["tool_choice"] = "auto"

        logger.info(f"🧠 [OpenRouterLLM] Sending Payload. Messages: {len(sanitized_messages)} | Tools: {bool(tools)}")

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
                                    
                                    # Suppress JSON leakage from speech token just in case
                                    if any(p in content for p in ['"arguments":', '{"name":', '"name":', '"id":', '": "']):
                                        logger.warning(f"🚫 [OpenRouterLLM] Filtered JSON leakage from speech token: {content[:20]}...")
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

            yield finish_obj

        except Exception as e:
            logger.error(f"❌ [OpenRouterLLM] Stream Error: {e}")
            yield {"type": "error", "content": str(e)}
