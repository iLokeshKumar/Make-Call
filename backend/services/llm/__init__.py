from .mistral import MistralLLM
from .claude import ClaudeLLM
from .gemini import GeminiLLM
from .perplexity import PerplexityLLM
from .cerebras import CerebrasLLM

def get_llm_service(provider: str, system_prompt: str):
    """Factory to get the requested LLM service."""
    provider = provider.lower()
    if provider == "mistral":
        return MistralLLM(system_prompt)
    elif provider == "anthropic" or provider == "claude":
        return ClaudeLLM(system_prompt)
    elif provider == "google" or provider == "gemini":
        return GeminiLLM(system_prompt)
    elif provider == "perplexity":
        return PerplexityLLM(system_prompt)
    elif provider == "cerebras":
        return CerebrasLLM(system_prompt)
    else:
        # Default fallback
        return MistralLLM(system_prompt)
