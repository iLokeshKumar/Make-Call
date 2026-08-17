import os
from dotenv import load_dotenv

load_dotenv()

DOMAIN = os.getenv("DOMAIN", "localhost")
if DOMAIN:
    DOMAIN = DOMAIN.replace("http://", "").replace("https://", "").replace("/", "")

PORT = int(os.getenv("PORT", 6060))

from credentials_service import get_credential


# Twilio
def get_twilio_client():
    from twilio.rest import Client as TwilioClient
    sid   = get_credential("TWILIO_ACCOUNT_SID")
    token = get_credential("TWILIO_AUTH_TOKEN")
    if not sid or not token:
        raise RuntimeError("Twilio credentials not configured. Go to Settings → Credentials.")
    return TwilioClient(sid, token)

def get_twilio_from_number() -> str | None:
    return get_credential("PHONE_NUMBER_FROM")


# Exotel
def get_exotel_api_key() -> str | None:
    return get_credential("EXOTEL_API_KEY")

def get_exotel_api_token() -> str | None:
    return get_credential("EXOTEL_API_TOKEN")

def get_exotel_account_sid() -> str | None:
    return get_credential("EXOTEL_ACCOUNT_SID")

def get_exophone() -> str | None:
    return get_credential("EXOPHONE")


# EnableX
def get_enablex_app_id() -> str | None:
    return get_credential("ENABLEX_APP_ID")

def get_enablex_app_key() -> str | None:
    return get_credential("ENABLEX_APP_KEY")

def get_enablex_from_number() -> str | None:
    return get_credential("ENABLEX_FROM_NUMBER")


# AI / LLM
def get_mistral_client():
    from mistralai import Mistral as MistralClient
    key = get_credential("MISTRAL_API_KEY")
    if not key:
        raise RuntimeError("Mistral API key not configured. Go to Settings → Credentials.")
    return MistralClient(api_key=key)

def get_gemini_api_key() -> str | None:
    return get_credential("GEMINI_API_KEY")

def get_cerebras_api_key() -> str | None:
    return get_credential("CEREBRAS_API_KEY")

def get_openrouter_api_key() -> str | None:
    return get_credential("OPENROUTER_API_KEY")


# STT
def get_deepgram_api_key() -> str | None:
    return get_credential("DEEPGRAM_API_KEY")

def get_deepgram_voice() -> str:
    return get_credential("DEEPGRAM_VOICE") or "aura-asteria-en"

def get_sarvam_api_key() -> str | None:
    return get_credential("SARVAM_API_KEY")


# TTS
def get_cartesia_api_key() -> str | None:
    return get_credential("CARTESIA_API_KEY")

def get_cartesia_voice_id() -> str:
    return get_credential("CARTESIA_VOICE_ID") or "a0e99841-438c-4a64-b679-ae501e7d6091"

def get_elevenlabs_api_key() -> str | None:
    return get_credential("ELEVENLABS_API_KEY")

def get_elevenlabs_voice_id() -> str:
    return get_credential("ELEVENLABS_VOICE_ID") or "CwhOLp6mAE7h9asvUURR"


# Data Enrichment
def get_apollo_api_key() -> str | None:
    return get_credential("APOLLO_API_KEY")
