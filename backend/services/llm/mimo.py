import logging
from openai import AsyncOpenAI
from typing import AsyncGenerator, List, Dict

logger = logging.getLogger(__name__)

class MimoLLM:
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        self.provider = "Mimo"
        self.system_prompt = system_prompt
        self.api_key = api_key
        self.model = model or "mimo-v2-pro"
        
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url="https://api.xiaomimimo.com/v1"
        )

    async def generate_response(self, messages: List[Dict], tools: List[Dict] = None) -> AsyncGenerator[str, None]:
        """Generates a streaming response from Mimo LLM."""
        try:
            formatted_messages = [{"role": "system", "content": self.system_prompt}] + messages
            
            # Remove any reasoning_content from previous assistant messages if present 
            # (assuming standard ChatCompletion format)
            for msg in formatted_messages:
                if msg.get("role") == "assistant" and "reasoning_content" in msg:
                    del msg["reasoning_content"]

            stream = await self.client.chat.completions.create(
                model=self.model,
                messages=formatted_messages,
                tools=tools if tools else None,
                stream=True
            )

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
                # Mimo often includes reasoning_content, which we can ignore for the final voice response
                # but it's good to know it exists for future debugging.

        except Exception as e:
            logger.error(f"❌ [MimoLLM] Error: {e}")
            yield f"I'm sorry, I encountered an error with the Mimo engine: {str(e)}"
