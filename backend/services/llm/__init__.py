from .mistral import MistralLLM
from .claude import ClaudeLLM
from .gemini import GeminiLLM
from .perplexity import PerplexityLLM
from .cerebras import CerebrasLLM
from .openrouter import OpenRouterLLM
from .mimo import MimoLLM

def get_llm_service(provider: str, system_prompt: str, api_key: str = None, model: str = None):
    """Factory to get the requested LLM service."""
    provider = provider.lower()
    if provider == "mistral":
        return MistralLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "anthropic" or provider == "claude":
        return ClaudeLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "google" or provider == "gemini":
        return GeminiLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "perplexity":
        return PerplexityLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "cerebras":
        return CerebrasLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "openrouter":
        return OpenRouterLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "mimo":
        return MimoLLM(system_prompt, api_key=api_key, model=model)
    else:
        # Default fallback
        return MistralLLM(system_prompt, api_key=api_key, model=model)
