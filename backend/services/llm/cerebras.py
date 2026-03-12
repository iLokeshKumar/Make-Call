import json
import logging
import aiohttp
import os
import asyncio
from types import SimpleNamespace
from typing import Optional, List, Dict, Any, AsyncGenerator
from .base import BaseLLM, SENTENCE_SPLIT_REGEX
from utils.config import CEREBRAS_API_KEY, CEREBRAS_MODEL

logger = logging.getLogger(__name__)

class CerebrasLLM(BaseLLM):
    def __init__(self, system_prompt: str):
        super().__init__(system_prompt)
        self.provider = "Cerebras"
        self.model = CEREBRAS_MODEL

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        url = "https://api.cerebras.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {CEREBRAS_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Deep-sanitize messages to ensure absolute JSON serialization
        def sanitize_obj(obj):
            if isinstance(obj, list):
                return [sanitize_obj(i) for i in obj]
            if isinstance(obj, dict):
                return {k: sanitize_obj(v) for k, v in obj.items()}
            if hasattr(obj, "__dict__"):
                return sanitize_obj(obj.__dict__)
            # Support for type('tc'...) objects from VoicePipeline
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

        # Context Truncation: Keep System Prompt + last 6 messages (lowers context usage)
        system_msg = [m for m in self.messages if m["role"] == "system"][:1]
        
        # Strengthen Cerebras instructions against JSON speech
        if system_msg:
            system_msg[0]["content"] += "\n\nCRITICAL: Never output tool calls, JSON, or markdown in your speech. Always use the provided tool-calling interface."
            
        other_msgs = [m for m in self.messages if m["role"] != "system"]
        truncated_msgs = other_msgs[-6:] if len(other_msgs) > 6 else other_msgs
        final_history = system_msg + truncated_msgs

        sanitized_messages = sanitize_obj(final_history)

        # Prepare payload
        payload = {
            "model": self.model,
            "messages": sanitized_messages,
            "stream": True,
            "temperature": 0.7,
            "max_tokens": 2048
        }
        
        if tools:
            # Ensure tools are also plain dicts
            payload["tools"] = sanitize_obj(tools)
            payload["tool_choice"] = "auto"

        logger.info(f"🧠 [CerebrasLLM] Sending Payload with {len(sanitized_messages)} messages.")
        
        if tools:
            # Ensure tools are also plain dicts
            payload["tools"] = sanitize_obj(tools)
            # Remove explicit tool_choice to see if it stabilizes Cerebras/Llama
            # payload["tool_choice"] = "auto"

        logger.info(f"🧠 [CerebrasLLM] Sending Payload. Messages: {len(sanitized_messages)} | Chars: {len(json.dumps(payload))} | Tools: {bool(tools)}")
        
        # Log roles for sequence verification
        roles = [m['role'] for m in sanitized_messages[-5:]]
        logger.debug(f"   Role sequence (last 5): {' -> '.join(roles)}")

        max_retries = 2
        retry_count = 0
        timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
        
        while retry_count <= max_retries:
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict = {}
                error_occurred = False

                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, headers=headers, json=payload) as resp:
                        if resp.status == 429:
                            retry_count += 1
                            if retry_count <= max_retries:
                                wait_time = retry_count * 2
                                logger.warning(f"⚠️ [CerebrasLLM] Rate Limited (429). Retrying in {wait_time}s...")
                                await asyncio.sleep(wait_time)
                                continue
                            else:
                                logger.error("❌ [CerebrasLLM] Rate Limit Exceeded after retries.")
                                yield {"type": "error", "content": "Cerebras API Rate Limited (429)"}
                                return
                        
                        if resp.status != 200:
                            error_text = await resp.text()
                            logger.error(f"❌ [CerebrasLLM] API Error {resp.status}: {error_text}")
                            yield {"type": "error", "content": f"Cerebras API Error {resp.status}"}
                            return

                        async for line in resp.content:
                            line = line.decode('utf-8').strip()
                            if not line or line == "data: [DONE]":
                                continue
                            
                            if line.startswith("data: "):
                                try:
                                    chunk = json.loads(line[6:])
                                    
                                    # Check for server errors mid-stream
                                    if "error" in chunk:
                                        err = chunk['error']
                                        logger.error(f"❌ [CerebrasLLM] Mid-stream Error: {err}")
                                        
                                        # If we haven't yielded any speech tokens yet, try a full retry
                                        if not full_reply and retry_count < max_retries:
                                            logger.warning("🔄 Attempting full retry since no tokens were spoken yet.")
                                            error_occurred = True # This will trigger the retry loop
                                            break
                                        
                                        yield {"type": "error", "content": "Cerebras server error mid-stream"}
                                        error_occurred = True
                                        break

                                    choices = chunk.get('choices', [])
                                    if not choices:
                                        continue

                                    delta = choices[0].get('delta', {})
                                    
                                    # 1. Content
                                    if 'content' in delta and delta['content']:
                                        content = delta['content']
                                        
                                        # JSON Speech Filter: Suppress metadata leak
                                        if '"arguments":' in content or '{"name":' in content or '"name":' in content:
                                            logger.warning(f"🚫 [CerebrasLLM] Filtered JSON leakage from speech: {content[:20]}...")
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

                                    # 2. Tool Calls
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
                                    logger.warning(f"⚠️ [CerebrasLLM] Chunk Parse Error: {e} | Line: {line}")

                if error_occurred:
                    return

                # Success - wrap up
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

                yield {
                    "type": "finished", 
                    "full_reply": full_reply, 
                    "tool_calls": formatted_tool_calls if formatted_tool_calls else None
                }
                return # Successful completion

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                retry_count += 1
                if retry_count <= max_retries:
                    wait_time = retry_count * 2
                    logger.warning(f"⚠️ [CerebrasLLM] Connection Error: {e}. Retrying in {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ [CerebrasLLM] Connection Failed after {max_retries} retries: {e}")
                    yield {"type": "error", "content": f"Connection Failure: {str(e)}"}
                    return
            except Exception as e:
                logger.error(f"❌ [CerebrasLLM] Unexpected Stream Error: {e}")
                yield {"type": "error", "content": str(e)}
                return
