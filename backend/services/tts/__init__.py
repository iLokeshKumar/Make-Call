from .elevenlabs import ElevenLabsTTS
from .cartesia import CartesiaTTS
from .sarvam import SarvamTTS
from .deepgram import DeepgramTTS

def get_tts_service(provider: str):
    """Factory to get the requested TTS service."""
    provider = provider.lower()
    if provider == "elevenlabs":
        return ElevenLabsTTS()
    elif provider == "cartesia":
        return CartesiaTTS()
    elif provider == "sarvam":
        return SarvamTTS()
    elif provider == "deepgram":
        return DeepgramTTS()
    else:
        # Default fallback
        return CartesiaTTS()
