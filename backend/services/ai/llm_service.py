import asyncio
import logging
import time
import json
import re
from typing import Optional, List, Dict, Any, AsyncGenerator
from utils.config import get_mistral_client

logger = logging.getLogger(__name__)

# Sentence/Phrase splitting regex for low-latency streaming. Splitting on commas and semicolons enables "prefix-emit" streaming to TTS providers.
SENTENCE_SPLIT_REGEX = re.compile(r'([.?!,;])\s+')

class LLMService:
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.messages = [{"role": "system", "content": system_prompt}]
        self.provider = "Mistral"
        self.model = "mistral-large-latest"

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str, tool_calls: Optional[List] = None):
        msg = {"role": "assistant", "content": content}
        if tool_calls:
            msg["tool_calls"] = tool_calls
        self.messages.append(msg)

    def add_tool_message(self, tool_call_id: str, name: str, content: str):
        self.messages.append({
            "role": "tool",
            "name": name,
            "content": content,
            "tool_call_id": tool_call_id
        })

    async def stream_mistral(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Streams response from Mistral. Yields either 'sentence', 'token', or 'tool_calls'.
        """
        try:
            accumulated_text = ""
            full_reply = ""
            tool_calls_dict = {}

            stream = await get_mistral_client().chat.stream_async(
                model="mistral-large-latest",
                messages=self.messages,
                tools=tools,
                max_tokens=2048, # Configurable
                temperature=0.7
            )

            async for chunk in stream:
                delta = chunk.data.choices[0].delta
                
                # 1. Handle Content
                if delta.content:
                    content = delta.content
                    accumulated_text += content
                    full_reply += content
                    # logger.debug(f"[Mistral Token] {content}") # Too noisy
                    yield {"type": "token", "content": content}

                    # Sentence boundary detection for TTS
                    parts = SENTENCE_SPLIT_REGEX.split(accumulated_text)
                    if len(parts) > 1:
                        sentence = parts[0] + parts[1]
                        accumulated_text = accumulated_text[len(sentence):]
                        if sentence.strip():
                            yield {"type": "sentence", "content": sentence.strip()}

                # 2. Handle Tool Calls
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_dict:
                            tool_calls_dict[idx] = tc
                        else:
                            tool_calls_dict[idx].function.arguments += tc.function.arguments

            # Final remaining chunk
            if accumulated_text.strip():
                logger.info(f"📤 [Mistral -> Queue] Final sentence: '{accumulated_text.strip()}'")
                yield {"type": "sentence", "content": accumulated_text.strip()}

            # End of stream metadata
            logger.info(f"✨ [Mistral Stream Finished] Full Reply: '{full_reply[:50]}...' Calls: {bool(tool_calls_dict)}")
            yield {
                "type": "finished", 
                "full_reply": full_reply, 
                "tool_calls": [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())] if tool_calls_dict else None
            }

        except Exception as e:
            logger.error(f"❌ [LLMService] Mistral Stream Error: {e}")
            yield {"type": "error", "content": str(e)}
