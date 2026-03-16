from .elevenlabs import ElevenLabsTTS
from .cartesia import CartesiaTTS
from .sarvam import SarvamTTS
from .deepgram import DeepgramTTS

def get_tts_service(provider: str, api_key: str = None, voice_id: str = None):
    """Factory to get the requested TTS service."""
    provider = provider.lower()
    if provider == "elevenlabs":
        return ElevenLabsTTS(api_key=api_key, voice_id=voice_id)
    elif provider == "cartesia":
        return CartesiaTTS(api_key=api_key, voice_id=voice_id)
    elif provider == "sarvam":
        return SarvamTTS(api_key=api_key, voice_id=voice_id) # sarvam might call it speaker but we'll adapt
    elif provider == "deepgram":
        return DeepgramTTS(api_key=api_key, voice_id=voice_id)
    else:
        # Default fallback
        return CartesiaTTS(api_key=api_key, voice_id=voice_id)
