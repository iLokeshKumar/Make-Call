from .mistral import MistralLLM
from .claude import ClaudeLLM
from .gemini import GeminiLLM
from .perplexity import PerplexityLLM
from .cerebras import CerebrasLLM
from .openrouter import OpenRouterLLM
from .mimo import MimoLLM
from .sarvam import SarvamLLM
from .groq import GroqLLM
from .azure import AzureLLM
from .smallest import SmallestLLM
from .airllm import AirLLMLLM

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
    elif provider == "sarvam":
        return SarvamLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "groq":
        return GroqLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "azure":
        return AzureLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "smallest":
        return SmallestLLM(system_prompt, api_key=api_key, model=model)
    elif provider == "airllm":
        return AirLLMLLM(system_prompt, api_key=api_key, model=model)
    else:
        # No silent fallback - misconfiguration must be loud or you end up
        # debugging "why is my Claude prompt answering like Mistral".
        raise ValueError(
            f"Unknown LLM provider: {provider!r}. "
            f"Valid: mistral, anthropic|claude, google|gemini, perplexity, "
            f"cerebras, openrouter, mimo, sarvam, groq, azure, smallest, airllm"
        )
