import json
import logging
import os
from typing import Optional, List, Dict, Any, AsyncGenerator
from openai import AsyncOpenAI
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)

class PerplexityLLM(BaseLLM):
    def __init__(self, system_prompt: str):
        super().__init__(system_prompt)
        self.provider = "Perplexity"
        self.model = "sonar-reasoning-pro" # Standard top-tier model
        self.client = AsyncOpenAI(
            api_key=os.getenv("PERPLEXITY_API_KEY"),
            base_url="https://api.perplexity.ai"
        )

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Perplexity currently has limited support for tool calling in their streaming API.
        Implementing standard text streaming for now.
        """
        try:
            accumulated_text = ""
            full_reply = ""

            # Perplexity uses OpenAI-compatible format
            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                stream=True
            )

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
