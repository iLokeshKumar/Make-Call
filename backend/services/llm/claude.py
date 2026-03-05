import json
import logging
import os
from typing import Optional, List, Dict, Any, AsyncGenerator
from anthropic import AsyncAnthropic
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)

class ClaudeLLM(BaseLLM):
    def __init__(self, system_prompt: str):
        super().__init__(system_prompt)
        self.provider = "Anthropic"
        self.model = os.getenv("Claude_API_ID", "claude-haiku-4-5-20251001")
        self.client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def _convert_tools(self, mistral_tools: List[Dict]) -> List[Dict]:
        """Convert OpenAI-style tools to Anthropic format."""
        claude_tools = []
        for tool in mistral_tools:
            if tool["type"] == "function":
                f = tool["function"]
                claude_tools.append({
                    "name": f["name"],
                    "description": f["description"],
                    "input_schema": f["parameters"]
                })
        return claude_tools

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            claude_tools = self._convert_tools(tools) if tools else None
            accumulated_text = ""
            full_reply = ""
            
            # Map messages to Claude format (system separate, roles 'user'/'assistant')
            claude_messages = [m for m in self.messages if m["role"] != "system"]
            system_msg = next((m["content"] for m in self.messages if m["role"] == "system"), "")

            async with self.client.messages.stream(
                model=self.model,
                max_tokens=2048,
                system=system_msg,
                messages=claude_messages,
                tools=claude_tools
            ) as stream:
                async for event in stream:
                    if event.type == "content_block_delta" and event.delta.type == "text_delta":
                        content = event.delta.text
                        accumulated_text += content
                        full_reply += content
                        yield {"type": "token", "content": content}

                        # Sentence splitting
                        parts = SENTENCE_SPLIT_REGEX.split(accumulated_text)
                        if len(parts) > 1:
                            sentence = parts[0] + parts[1]
                            accumulated_text = accumulated_text[len(sentence):]
                            if sentence.strip():
                                yield {"type": "sentence", "content": sentence.strip()}

                # Handle final tool calls if any
                final_msg = await stream.get_final_message()
                tool_calls = []
                for content_block in final_msg.content:
                    if content_block.type == "tool_use":
                        # Convert to Mistral/OpenAI style for the pipeline
                        tool_calls.append(type('tc', (), {
                            'id': content_block.id,
                            'function': type('fn', (), {
                                'name': content_block.name,
                                'arguments': json.dumps(content_block.input)
                            })
                        }))

                # Final sentence
                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                yield {
                    "type": "finished",
                    "full_reply": full_reply,
                    "tool_calls": tool_calls if tool_calls else None
                }

        except Exception as e:
            logger.error(f"❌ [ClaudeLLM] Stream Error: {e}")
            yield {"type": "error", "content": str(e)}
