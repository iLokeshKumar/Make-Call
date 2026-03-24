from .elevenlabs import ElevenLabsTTS
from .cartesia import CartesiaTTS
from .sarvam import SarvamTTS
from .deepgram import DeepgramTTS
from .mimo import MimoTTS

def get_tts_service(provider: str, api_key: str = None, voice_id: str = None, model: str = None):
    """Factory to get the requested TTS service."""
    provider = provider.lower()
    if provider == "elevenlabs":
        return ElevenLabsTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "cartesia":
        return CartesiaTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "sarvam":
        return SarvamTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "deepgram":
        return DeepgramTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "mimo":
        return MimoTTS(api_key=api_key, voice_id=voice_id, model=model)
    else:
        # Default fallback
        return CartesiaTTS(api_key=api_key, voice_id=voice_id, model=model)
