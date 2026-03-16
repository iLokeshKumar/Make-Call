import json
import logging
import os
from typing import Optional, List, Dict, Any, AsyncGenerator
from openai import AsyncOpenAI
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)

class PerplexityLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Perplexity"
        self.model = model or "sonar-reasoning-pro" # Standard top-tier model
        self.api_key = api_key
        
        if not self.api_key:
            logger.warning("PerplexityLLM initialized without an API key! Streams will fail.")

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.perplexity.ai"
        ) if self.api_key else None

    def _convert_tools(self, mistral_tools: List[Dict]) -> List[Dict]:
        """Convert OpenAI-style tools to Perplexity (OpenAI compatible) format."""
        formatted_tools = []
        for t in mistral_tools:
            if hasattr(t, "to_dict"):
                formatted_tools.append(t.to_dict())
            elif isinstance(t, dict):
                formatted_tools.append(t)
        return formatted_tools

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            formatted_tools = self._convert_tools(tools) if tools else None
            accumulated_text = ""
            full_reply = ""

            # Perplexity uses OpenAI-compatible format
            payload = {
                "model": self.model,
                "messages": self.messages,
                "stream": True
            }
            if formatted_tools:
                payload["tools"] = formatted_tools
                payload["tool_choice"] = "auto"

            stream = await self.client.chat.completions.create(**payload)

            async for chunk in stream:
                if not chunk.choices: continue
                delta = chunk.choices[0].delta
                
                if delta.content:
                    content = delta.content
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

            # Final remaining chunk
            if accumulated_text.strip():
                yield {"type": "sentence", "content": accumulated_text.strip()}

            yield {
                "type": "finished", 
                "full_reply": full_reply, 
                "tool_calls": None # Perplexity tools are still in beta/limited
            }

        except Exception as e:
            logger.error(f"❌ [PerplexityLLM] Stream Error: {e}")
            yield {"type": "error", "content": str(e)}
