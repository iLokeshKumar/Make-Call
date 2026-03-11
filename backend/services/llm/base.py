import logging
import re
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, AsyncGenerator

logger = logging.getLogger(__name__)

# Sentence splitting regex for low-latency streaming
SENTENCE_SPLIT_REGEX = re.compile(r'([.?!,;])\s+')

class BaseLLM(ABC):
    def __init__(self, system_prompt: str):
        self.system_prompt = system_prompt
        self.messages = [{"role": "system", "content": system_prompt}]
        self.provider = "Unknown"
        self.model = "Unknown"

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str, tool_calls: Optional[List] = None):
        if not content and not tool_calls:
            logger.warning("⚠️ [BaseLLM] Attempted to add an empty assistant message (no content and no tools). Skipping.")
            return

        msg = {"role": "assistant", "content": content or ""}
        if tool_calls:
            # Sanitize tool_calls: Convert any non-dict objects (SimpleNamespace, SDK objects) to plain dicts
            sanitized_calls = []
            for tc in tool_calls:
                if isinstance(tc, dict):
                    sanitized_calls.append(tc)
                else:
                    # Convert object to dict (handles SimpleNamespace and type('tc', ...) objects)
                    try:
                        sanitized_calls.append({
                            "id": getattr(tc, "id", None),
                            "type": "function",
                            "function": {
                                "name": getattr(tc.function, "name", None),
                                "arguments": getattr(tc.function, "arguments", None)
                            }
                        })
                    except Exception as e:
                        logger.warning(f"⚠️ [BaseLLM] Failed to sanitize tool call object: {e}")
                        sanitized_calls.append(tc)
            msg["tool_calls"] = sanitized_calls
        self.messages.append(msg)

    def add_tool_message(self, tool_call_id: str, name: str, content: str):
        self.messages.append({
            "role": "tool",
            "name": name,
            "content": content,
            "tool_call_id": tool_call_id
        })

    @abstractmethod
    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Streams response from the LLM. Yields Dict with 'type' and 'content'.
        Possible types: 'token', 'sentence', 'finished', 'error'.
        """
        pass

    def _split_sentences(self, text: str, accumulated_text: str):
        """Helper to split text into sentences for TTS streaming."""
        full_text = accumulated_text + text
        parts = SENTENCE_SPLIT_REGEX.split(full_text)
        
        sentences = []
        remaining = full_text
        
        if len(parts) > 1:
            # Join parts back while keeping delimiters
            # parts looks like: ["Hello", ".", " How are you", "?", " I'm fine"]
            for i in range(0, len(parts) - 1, 2):
                sentence = parts[i] + parts[i+1]
                sentences.append(sentence.strip())
                remaining = full_text[len("".join(parts[:i+2])):]
        
        return sentences, remaining
