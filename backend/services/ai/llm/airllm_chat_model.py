"""
LangChain BaseChatModel wrapper around AirLLM for agent orchestration
(ISM, post-call, supervisor graph nodes).
"""
import asyncio
import logging
from typing import Any, List, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from .airllm_provider import format_prompt, generate_sync

logger = logging.getLogger(__name__)


def _lc_to_openai(msgs: List[BaseMessage]) -> list:
    out = []
    for m in msgs:
        if isinstance(m, SystemMessage):
            out.append({"role": "system", "content": m.content})
        elif isinstance(m, HumanMessage):
            out.append({"role": "user", "content": m.content})
        elif isinstance(m, AIMessage):
            out.append({"role": "assistant", "content": m.content})
        else:
            out.append({"role": "user", "content": str(m.content)})
    return out


class AirLLMChatModel(BaseChatModel):
    model_name: str = "airllm-local"

    def _generate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = format_prompt(_lc_to_openai(messages))
        text = generate_sync(prompt)
        if stop:
            for s in stop:
                if s in text:
                    text = text[: text.index(s)]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    async def _agenerate(
        self,
        messages: List[BaseMessage],
        stop: Optional[List[str]] = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        loop = asyncio.get_event_loop()
        prompt = format_prompt(_lc_to_openai(messages))
        text = await loop.run_in_executor(None, generate_sync, prompt)
        if stop:
            for s in stop:
                if s in text:
                    text = text[: text.index(s)]
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=text))])

    @property
    def _llm_type(self) -> str:
        return "airllm"
