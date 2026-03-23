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
    def update_system_prompt(self, new_prompt: str):
        """Updates the system prompt and the first message in the history."""
        self.system_prompt = new_prompt
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0]["content"] = new_prompt
        else:
            self.messages.insert(0, {"role": "system", "content": new_prompt})
        logger.info("📝 [BaseLLM] System prompt updated dynamically")

    def add_user_message(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str, tool_calls: Optional[List] = None, reasoning_details: Optional[str] = None):
        if not content and not tool_calls:
            logger.warning("⚠️ [BaseLLM] Attempted to add an empty assistant message (no content and no tools). Skipping.")
            return

        msg = {"role": "assistant", "content": content or ""}
        
        if reasoning_details:
            msg["reasoning_details"] = reasoning_details
            
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

    def clean_interrupted_tool_calls(self):
        """
        Removes tool_calls from the last assistant message if they haven't been fulfilled.
        Prevents 'Not the same number of function calls and responses' errors during barge-in.
        """
        if not self.messages:
            return

        last_msg = self.messages[-1]
        
        # If the last message is an assistant message with tool_calls
        if last_msg.get("role") == "assistant" and last_msg.get("tool_calls"):
            # Check if there are corresponding 'tool' messages in the history
            tool_call_ids = {tc.get("id") for tc in last_msg.get("tool_calls", []) if tc.get("id")}
            
            # Since LLM protocol requires tool messages to follow immediately, 
            # if the NEXT message is not a tool message, it's an interrupted sequence.
            # However, the user might have already spoken (next message is 'user').
            # Simply: if no tool messages followed, it's interrupted.
            
            # We look for ANY tool messages that follow this assistant message.
            # But in our case, if it's the LAST message, it's definitely interrupted.
            logger.info(f"🧹 [BaseLLM] Cleaning interrupted tool calls from last assistant message.")
            last_msg.pop("tool_calls", None)
            # Optional: if the content is also empty, we might want to remove the message entirely,
            # but usually it has a "Thinking..." phrase.

    def get_safe_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Returns a truncated message history that is safe for tool-calling models.
        Ensures that 'tool' messages are never orphaned from their parent 'assistant' tool_calls.
        """
        if len(self.messages) <= 1:
            return self.messages

        # Separate system prompt
        system_msgs = [m for m in self.messages if m.get("role") == "system"]
        other_msgs = [m for m in self.messages if m.get("role") != "system"]

        if len(other_msgs) <= limit:
            return system_msgs + other_msgs

        # Initial slice
        truncated = other_msgs[-limit:]
        
        # Check if we started in the middle of a tool chain
        # 1. If first message is 'tool', we MUST go back to find the assistant message
        # 2. If first message is 'assistant' with tool_calls, we are okay
        
        while truncated and truncated[0].get("role") == "tool":
            # Find how many more messages we need to reach the previous one
            current_len = len(truncated)
            target_len = current_len + 1
            if target_len > len(other_msgs):
                break
            truncated = other_msgs[-target_len:]
            
        # Re-check: Even if we found an assistant message, was it a tool_call message?
        # If the first message is 'assistant' but it's part of a sequence that ends in a tool result we already have,
        # we are technically safe, but some models prefer the user message too.
        # For now, ensuring no orphaned 'tool' roles is the primary fix for 422.
        
        return system_msgs + truncated

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
