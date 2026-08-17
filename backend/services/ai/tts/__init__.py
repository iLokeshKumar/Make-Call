from .voicebox import VoiceboxTTS
from .elevenlabs import ElevenLabsTTS
from .cartesia import CartesiaTTS
from .sarvam import SarvamTTS
from .deepgram import DeepgramTTS
from .mimo import MimoTTS
from .mistral import MistralTTS
from .smallest import SmallestTTS
from .groq import GroqTTS
from .rime import RimeTTS
from .polly import PollyTTS
from .azure import AzureTTS
from .inworld import InworldTTS
from .kitten import KittenTTS
from .vachana import VachanaTTS


def get_tts_service(provider: str, api_key: str = None, voice_id: str = None, model: str = None):
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
    elif provider == "mistral":
        return MistralTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "smallest":
        return SmallestTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "groq":
        return GroqTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "rime":
        return RimeTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "polly":
        return PollyTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "azure":
        return AzureTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "inworld":
        return InworldTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "kitten":
        return KittenTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "vachana":
        return VachanaTTS(api_key=api_key, voice_id=voice_id, model=model)
    elif provider == "voicebox":
        return VoiceboxTTS(api_key=api_key, voice_id=voice_id, model=model)
    else:
        # Default fallback
        return CartesiaTTS(api_key=api_key, voice_id=voice_id, model=model)
