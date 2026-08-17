"""
LangChain LLM factory — returns the right ChatModel for a company's settings.

Reads LLM_PROVIDER + model name + API key from CompanySetting (with settings_cache).
Falls back to Gemini Flash if no setting is found.

Supported providers: gemini, mistral, anthropic, openai, openrouter, cerebras
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlmodel import Session

logger = logging.getLogger(__name__)

# Provider → (model_key, api_key_key, default_model)
_PROVIDER_MAP: dict[str, tuple[str, str, str]] = {
    "gemini":     ("GEMINI_MODEL",    "GEMINI_API_KEY",    "gemini-2.0-flash"),
    "mistral":    ("MISTRAL_MODEL",   "MISTRAL_API_KEY",   "mistral-small-latest"),
    "anthropic":  ("ANTHROPIC_MODEL", "ANTHROPIC_API_KEY", "claude-haiku-4-5-20251001"),
    "openai":     ("OPENAI_MODEL",    "OPENAI_API_KEY",    "gpt-4o-mini"),
    "openrouter": ("OPENROUTER_MODEL","OPENROUTER_API_KEY","openai/gpt-4o-mini"),
    "cerebras":   ("CEREBRAS_MODEL",  "CEREBRAS_API_KEY",  "llama-3.3-70b"),
    "airllm":     ("AIRLLM_MODEL",    "AIRLLM_HF_TOKEN",   ""),
}


def _get_setting(session: Session, company_id: int, key: str) -> Optional[str]:
    """Read a CompanySetting via cache-first lookup."""
    from utils import settings_cache as _sc
    cached = _sc.get(key, user_id=company_id)
    if cached is not None:
        return cached
    from sqlmodel import select
    from models.models import CompanySetting
    from utils.encryption import decrypt_value
    row = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == company_id,
            CompanySetting.key == key,
        )
    ).first()
    if not row:
        return None
    return decrypt_value(row.value) if row.is_secret else row.value


def get_agent_llm(session: Session, company_id: int):
    """
    Return a LangChain ChatModel based on the company's LLM_PROVIDER setting.

    The returned model is bound to the company's API key so agents
    don't share credentials across tenants.
    """
    provider = (_get_setting(session, company_id, "LLM_PROVIDER") or "gemini").lower().strip()

    if provider not in _PROVIDER_MAP:
        logger.warning("[LLMFactory] Unknown provider '%s', falling back to gemini", provider)
        provider = "gemini"

    model_key, api_key_key, default_model = _PROVIDER_MAP[provider]
    model_name = _get_setting(session, company_id, model_key) or default_model
    api_key = _get_setting(session, company_id, api_key_key)

    logger.debug("[LLMFactory] company=%d provider=%s model=%s", company_id, provider, model_name)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        kwargs = {"model": model_name}
        if api_key:
            kwargs["google_api_key"] = api_key
        return ChatGoogleGenerativeAI(**kwargs)

    if provider == "mistral":
        from langchain_mistralai import ChatMistralAI
        kwargs = {"model": model_name}
        if api_key:
            kwargs["api_key"] = api_key
        return ChatMistralAI(**kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        kwargs = {"model": model_name}
        if api_key:
            kwargs["api_key"] = api_key
        return ChatAnthropic(**kwargs)

    if provider in ("openai", "openrouter"):
        from langchain_openai import ChatOpenAI
        kwargs: dict = {"model": model_name}
        if api_key:
            kwargs["api_key"] = api_key
        if provider == "openrouter":
            kwargs["base_url"] = "https://openrouter.ai/api/v1"
        return ChatOpenAI(**kwargs)

    if provider == "cerebras":
        from langchain_openai import ChatOpenAI
        kwargs = {
            "model": model_name,
            "base_url": "https://api.cerebras.ai/v1",
        }
        if api_key:
            kwargs["api_key"] = api_key
        return ChatOpenAI(**kwargs)

    if provider == "airllm":
        from services.ai.llm.airllm_chat_model import AirLLMChatModel
        return AirLLMChatModel()

    # Should never reach here given the guard above
    raise ValueError(f"Unhandled provider: {provider}")
