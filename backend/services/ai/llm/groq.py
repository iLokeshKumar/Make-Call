import asyncio
import logging
import re as _re
import uuid as _uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

from groq import AsyncGroq

from .base import BaseLLM, SENTENCE_SPLIT_REGEX

logger = logging.getLogger(__name__)


class GroqLLM(BaseLLM):
    def __init__(self, system_prompt: str, api_key: str = None, model: str = None):
        super().__init__(system_prompt)
        self.provider = "Groq"

        self.model = model or "llama-3.3-70b-versatile"
        self.api_key = api_key

        if not self.api_key:
            logger.warning("GroqLLM initialized without an API key! Streams will fail.")

        self.client = AsyncGroq(api_key=self.api_key) if self.api_key else None

    async def stream(
        self,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        if not self.client:
            raise ValueError("Groq Client is not initialized due to missing API key")

        max_retries = 3
        current_tools = tools
        for attempt in range(max_retries):
            try:
                accumulated_text = ""
                full_reply = ""
                tool_calls_dict: Dict[int, Any] = {}

                # Clean up any unfulfilled tool calls from previous (interrupted) turns
                self.clean_interrupted_tool_calls()

                stream = await self.client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    tools=current_tools,
                    max_completion_tokens=2048,
                    temperature=0.7,
                    stream=True,
                )

                async for chunk in stream:
                    if not chunk.choices:
                        continue

                    delta = chunk.choices[0].delta

                    # Content
                    content = getattr(delta, "content", None)
                    if content:
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

                    # Tool calls — key by index (Groq streaming deltas only carry id/name on the first chunk; subsequent chunks carry argument fragments and share the same index).
                    tc_list = getattr(delta, "tool_calls", None)
                    if tc_list:
                        for tc in tc_list:
                            idx = getattr(tc, "index", None)
                            if idx is None:
                                continue

                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = tc
                            else:
                                existing_fn = getattr(tool_calls_dict[idx], "function", None)
                                new_fn = getattr(tc, "function", None)
                                if existing_fn and new_fn:
                                    new_args = getattr(new_fn, "arguments", "") or ""
                                    if new_args:
                                        existing_fn.arguments = (existing_fn.arguments or "") + new_args

                # Final remaining chunk
                if accumulated_text.strip():
                    yield {"type": "sentence", "content": accumulated_text.strip()}

                # End of stream metadata
                yield {
                    "type": "finished",
                    "full_reply": full_reply,
                    "tool_calls": [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())] if tool_calls_dict else None,
                }
                # Clean up any no-tools-mode injection added during a failed attempt.
                _no_tools_msg = "Do NOT use any function or tool call syntax. Respond only in plain conversational text."
                self.messages = [m for m in self.messages if not (m.get("role") == "system" and m.get("content") == _no_tools_msg)]
                return

            except Exception as exc:
                logger.error("❌ [GroqLLM] Stream Error: %s", exc)
                err_str = str(exc)

                # Groq rejects tool calls where the model embeds args in the name field,
                # e.g. name='get_product_info {"product_name": "..."}'. Parse and recover.
                tc_match = _re.search(
                    r"attempted to call tool '(\w+)\s*(\{.*?\})'\s+which was not in request\.tools",
                    err_str, _re.DOTALL,
                )
                if tc_match:
                    recovered_name = tc_match.group(1)
                    recovered_args = tc_match.group(2)
                    logger.warning(
                        "[GroqLLM] Recovering malformed tool call: name=%s args=%s",
                        recovered_name, recovered_args[:80],
                    )
                    try:
                        from groq.types.chat.chat_completion_message_tool_call import (
                            ChatCompletionMessageToolCall,
                            Function,
                        )
                        synthetic_tc = ChatCompletionMessageToolCall(
                            id=f"call_{_uuid.uuid4().hex[:8]}",
                            type="function",
                            function=Function(name=recovered_name, arguments=recovered_args),
                        )
                        yield {
                            "type": "finished",
                            "full_reply": full_reply,
                            "tool_calls": [synthetic_tc],
                        }
                        return
                    except Exception as parse_exc:
                        logger.error("[GroqLLM] Tool call recovery failed: %s", parse_exc)

                # Model generated invalid function call format — strip tools and retry plain.
                if "Failed to call a function" in err_str and attempt < max_retries - 1:
                    logger.warning(
                        "[GroqLLM] Function call format failure — retrying without tools (attempt %s)",
                        attempt + 1,
                    )
                    current_tools = None
                    # Inject instruction so model doesn't hallucinate function call syntax.
                    self.messages.append({
                        "role": "system",
                        "content": "Do NOT use any function or tool call syntax. Respond only in plain conversational text.",
                    })
                    await asyncio.sleep(1.0)
                    continue

                if "429" in err_str and attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1, 2, 4
                    logger.warning(
                        "⚠️ [GroqLLM] Rate limited. Waiting %ss before retry %s...",
                        wait,
                        attempt + 1,
                    )
                    await asyncio.sleep(wait)
                    continue

                yield {"type": "error", "content": err_str}
                return
