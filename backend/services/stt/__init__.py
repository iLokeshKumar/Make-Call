from .deepgram import DeepgramSTT
from .sarvam import SarvamSTT
from .cartesia import CartesiaSTT

def get_stt_service(provider: str):
    """Factory to get the requested STT service."""
    provider = provider.lower()
    if provider == "deepgram":
        return DeepgramSTT()
    elif provider == "sarvam":
        return SarvamSTT()
    elif provider == "cartesia":
        return CartesiaSTT()
    else:
        # Default fallback
        return DeepgramSTT()
