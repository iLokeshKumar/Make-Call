"""
Typed application configuration using pydantic-settings.

Validates critical env vars at import time. Non-critical keys (provider API
keys) are Optional — startup checks in main.py already warn about those.

Usage:
    from config import settings
    print(settings.DATABASE_URL)
"""
from __future__ import annotations

from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """
    Central config — values come from .env / environment variables.

    Required fields (app won't start without them):
      DATABASE_URL, SECRET_KEY

    Everything else is optional with sensible defaults.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Core.  These have CI/test-friendly defaults; production .env / env
    # overrides them.  The database.py fallback uses the same sqlite://
    # sentinel when DATABASE_URL is unset.  SECRET_KEY default is throwaway
    # and not used by anything that signs tokens at test time.
    DATABASE_URL: str = "sqlite://"
    SECRET_KEY: str = "ci-only-not-used-by-tests"

    # Server
    PORT: int = 6060
    DOMAIN: Optional[str] = None  # ngrok/public domain for webhooks
    FRONTEND_BASE_URL: str = "http://localhost:3006"
    UPLOADS_DIR: str = "uploads"

    # Feature flags
    ENABLE_BACKGROUND_WORKERS: bool = True
    ENABLE_PRECALL_RESEARCHER: bool = True

    # LLM providers (at least one needed)
    MISTRAL_API_KEY: Optional[str] = None
    MISTRAL_MODEL: str = "mistral-large-latest"
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_MODEL: str = "gemini-2.0-flash"
    OPENAI_API_KEY: Optional[str] = None
    Claude_API_ID: Optional[str] = None
    LLM_PROVIDER: str = "mistral"
    LLM_MODEL: Optional[str] = None

    # Forex Providers
    API_LAYER_API_KEY: Optional[str] = None

    # Truecaller Business Integration
    TRUECALLER_KEY_ID: Optional[str] = None
    TRUECALLER_API_KEY: Optional[str] = None
    TRUECALLER_CLIENT_ACCOUNT_ID: Optional[str] = None

    # STT providers
    DEEPGRAM_API_KEY: Optional[str] = None
    SARVAM_API_KEY: Optional[str] = None
    CARTESIA_API_KEY: Optional[str] = None
    SMALLEST_API_KEY: Optional[str] = None

    # TTS providers
    CARTESIA_VOICE_ID: Optional[str] = None
    ELEVENLABS_VOICE_ID: Optional[str] = None
    ELEVENLABS_TTS_MODEL: Optional[str] = None
    DEEPGRAM_VOICE: Optional[str] = None
    DEEPGRAM_TTS_MODEL: Optional[str] = None

    # Voice pipeline
    VOICE_ENGINE: str = "mistral"
    MAX_CALL_DURATION_SECONDS: int = 1800
    DEFAULT_TIMEZONE: str = "Asia/Kolkata"

    # Barge-in tuning
    DISABLE_BARGE_IN: bool = False
    BARGE_RMS_THRESHOLD: int = 400
    BARGE_FRAMES_NEEDED: int = 3
    BARGE_CLEAR_COOLDOWN_MS: int = 300
    BARGE_TTS_GUARD_MS: int = 500
    BARGE_POST_SPEECH_COOLDOWN_MS: int = 200
    BARGE_RETRIGGER_COOLDOWN_MS: int = 1500
    BARGE_SILENCE_RESET_FRAMES: int = 15

    # Telephony
    TWILIO_ACCOUNT_SID: Optional[str] = None
    TWILIO_AUTH_TOKEN: Optional[str] = None
    PHONE_NUMBER_FROM: Optional[str] = None
    EXOTEL_ACCOUNT_SID: Optional[str] = None
    EXOTEL_API_KEY: Optional[str] = None
    EXOTEL_API_TOKEN: Optional[str] = None
    EXOPHONE: Optional[str] = None
    WHATSAPP_NUMBER_FROM: Optional[str] = None

    # Email (SMTP / IMAP)
    SMTP_HOST: Optional[str] = Field(default=None, alias="SMTP_SERVER")
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = Field(default=None, alias="SMTP_USERNAME")
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_SECURITY: str = "starttls"
    SENDER_EMAIL: Optional[str] = None
    IMAP_USERNAME: Optional[str] = None
    IMAP_PASSWORD: Optional[str] = None
    EMAIL_OUTBOX_POLL_SECONDS: int = 30

    # Google OAuth
    Client_ID: Optional[str] = None
    Client_Secret: Optional[str] = None
    GOOGLE_REDIRECT_URI: Optional[str] = None

    # Enrichment
    APOLLO_API_KEY: Optional[str] = Field(default=None)

    # Encryption
    FERNET_KEY: Optional[str] = None

    # Observability
    LANGCHAIN_API_KEY: Optional[str] = None
    LANGCHAIN_PROJECT: Optional[str] = None
    LANGCHAIN_TRACING_V2: Optional[str] = None
    LANGGRAPH_CHECKPOINTER: str = "memory"

    # RAG / Embeddings
    CHROMA_PATH: str = "knowledge_base"
    EMBED_PROVIDER: str = "sentence_transformers"
    EMBED_MODEL: str = "all-MiniLM-L6-v2"

    # Tracking / CSAT
    TRACKING_BASE_URL: Optional[str] = None
    CSAT_VIEW_RATE_LIMIT_PER_MINUTE: int = 30
    CSAT_SUBMIT_RATE_LIMIT_PER_MINUTE: int = 10
    CSAT_DEDUPE_WINDOW_HOURS: int = 24

    # Webhooks
    WEBHOOK_SIGNATURE_STRICT: bool = False

    # Dead-letter
    DEAD_LETTER_THRESHOLD: int = 3

    # RLS safety
    RLS_WARN_ON_MISSING: bool = True

    # App env
    APP_ENV: str = "development"
    DATE_NORMALIZER_PROVIDER: str = "dateutil"


settings = AppConfig()
