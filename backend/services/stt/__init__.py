from .deepgram import DeepgramSTT
from .sarvam import SarvamSTT
from .cartesia import CartesiaSTT

def get_stt_service(provider: str, api_key: str = None, model: str = None):
    """Factory to get the requested STT service."""
    provider = provider.lower()
    if provider == "deepgram":
        return DeepgramSTT(api_key=api_key, model=model)
    elif provider == "sarvam":
        return SarvamSTT(api_key=api_key, model=model)
    elif provider == "cartesia":
        return CartesiaSTT(api_key=api_key, model=model)
    else:
        # Default fallback
        return DeepgramSTT(api_key=api_key, model=model)
