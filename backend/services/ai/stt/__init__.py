from .voicebox import VoiceboxSTT
from .deepgram import DeepgramSTT
from .sarvam import SarvamSTT
from .cartesia import CartesiaSTT
from .elevenlabs import ElevenLabsSTT
from .smallest import SmallestSTT
from .groq import GroqSTT
from .gladia import GladiaSTT
from .ringg_ai import RinggAISTT
from .assemblyai import AssemblyAISTT
from .azure import AzureSTT
from .inworld import InworldSTT
from .vachana import VachanaSTT


def get_stt_service(provider: str, api_key: str = None, model: str = None):
    provider = provider.lower()
    if provider == "deepgram":
        return DeepgramSTT(api_key=api_key, model=model)
    elif provider == "sarvam":
        return SarvamSTT(api_key=api_key, model=model)
    elif provider == "azure":
        return AzureSTT(api_key=api_key, model=model)
    elif provider == "cartesia":
        return CartesiaSTT(api_key=api_key, model=model)
    elif provider == "elevenlabs":
        return ElevenLabsSTT(api_key=api_key, model=model)
    elif provider == "smallest":
        return SmallestSTT(api_key=api_key, model=model)
    elif provider == "groq":
        return GroqSTT(api_key=api_key, model=model)
    elif provider == "gladia":
        return GladiaSTT(api_key=api_key, model=model)
    elif provider == "ringg_ai":
        return RinggAISTT(api_key=api_key, model=model)
    elif provider == "assemblyai":
        return AssemblyAISTT(api_key=api_key, model=model)
    elif provider == "inworld":
        return InworldSTT(api_key=api_key, model=model)
    elif provider == "vachana":
        return VachanaSTT(api_key=api_key, model=model)
    elif provider == "voicebox":
        return VoiceboxSTT(api_key=api_key, model=model)
    else:
        return DeepgramSTT(api_key=api_key, model=model)