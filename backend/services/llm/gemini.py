import json
import logging
import os
import asyncio
from typing import Optional, List, Dict, Any, AsyncGenerator
from google import genai
from google.genai import types
from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)

class GeminiLLM(BaseLLM):
    def __init__(self, system_prompt: str):
        super().__init__(system_prompt)
        self.provider = "Google"
        self.model = "gemini-1.5-flash"
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    def _convert_tools(self, mistral_tools: List[Dict]) -> List:
        """Convert OpenAI-style tools to Gemini format for the new SDK."""
        # The new SDK takes a list of types.Tool objects or function declaration dicts
        gemini_tools = []
        for tool in mistral_tools:
            if tool["type"] == "function":
                f = tool["function"]
                # New SDK accepts function declarations as dicts or types.FunctionDeclaration
                gemini_tools.append({
                    "name": f["name"],
                    "description": f["description"],
                    "parameters": f["parameters"]
                })
        # Note: New SDK client.aio.models.generate_content_stream expects tools as a list of types.Tool
        return [types.Tool(function_declarations=gemini_tools)] if gemini_tools else None

    async def stream(self, tools: Optional[List] = None) -> AsyncGenerator[Dict[str, Any], None]:
        try:
            gemini_tools = self._convert_tools(tools) if tools else None
            accumulated_text = ""
            full_reply = ""
            
            # Convert messages to Gemini format (user -> "user", model -> "model")
            # Note: system instruction is passed in config
            contents = []
            for msg in self.messages:
                if msg["role"] == "system": continue
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))

            # New SDK uses client.aio for async
            config = types.GenerateContentConfig(
                system_instruction=self.system_prompt,
                tools=gemini_tools
            )

            response = await self.client.aio.models.generate_content_stream(
                model=self.model,
                contents=contents,
                config=config
            )

            tool_calls = []
            async for chunk in response:
                if chunk.candidates[0].content and chunk.candidates[0].content.parts:
                    for part in chunk.candidates[0].content.parts:
                        if part.text:
                            content = part.text
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
                        
                        if part.call:
                            # Handling tool calls in the new SDK
                            # New SDK uses 'call' instead of 'function_call'
                            tool_calls.append(type('tc', (), {
                                'id': f"call_{int(asyncio.get_event_loop().time()*1000)}",
                                'function': type('fn', (), {
                                    'name': part.call.name,
                                    'arguments': json.dumps(dict(part.call.args))
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
            logger.error(f"❌ [GeminiLLM] Stream Error: {e}")
            yield {"type": "error", "content": str(e)}
