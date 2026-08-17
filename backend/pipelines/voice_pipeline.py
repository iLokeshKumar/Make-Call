import asyncio
import base64
import json
import logging
import os
import re
import time
import uuid as _uuid
from datetime import datetime
from collections import deque
from typing import Any, Dict, List, Optional

import aiohttp
import audioop
from sqlmodel import Session, select

from models.models import CompanySetting, Interaction, LatencyLog, Lead, User, utc_now
from services.voice.mark_tracking_service import enqueue_mark as _enqueue_mark
from services.platform.cost_service import calculate_call_cost as _calc_cost, save_cost_record as _save_cost
from services.ai.llm import get_llm_service
from agents._format_utils import to_compact
from services.ai.stt import get_stt_service
from services.ai.tts import get_tts_service
from tool_adapter import execute_mcp_tool, get_mistral_tools
from utils.encryption import decrypt_value
from utils.audio import clean_voice_text
from utils.lead_utils import get_comprehensive_lead_context
from utils.timezone_utils import format_datetime_for_timezone, resolve_lead_timezone
from utils import settings_cache as _sc
from services.call import sentiment_broadcaster
from pipelines.voice.stt_handler import STTHandler
from pipelines.voice.tts_handler import TTSHandler
from pipelines.voice.llm_handler import LLMHandler
from pipelines.voice.interrupt_manager import InterruptManager
from pipelines.voice.transcript_manager import TranscriptManager
from pipelines.voice.graph_pipeline_adapter import (
    create_graph_engine_from_runtime,
    should_use_graph_engine,
    process_graph_turn,
)
from services.voice.voicemail_handler import VoicemailHandler
from services.voice.language.language_detector import LanguageDetector
from services.voice.filler_service import FillerService
from services.voice.ambient_noise_service import AmbientNoiseService
from communicators.plivo import PlivoCommunicator
from communicators.vobiz import VobizCommunicator

logger = logging.getLogger(__name__)


_SETTINGS_CACHE_SENTINEL = "__cache_loaded__"


def _load_company_settings(session: Session, company_id: int | None) -> dict[str, str]:
    if not company_id:
        return {}


    if _sc.get(_SETTINGS_CACHE_SENTINEL, user_id=company_id) is not None:
        result = _sc.get_all(user_id=company_id)
        result.pop(_SETTINGS_CACHE_SENTINEL, None)
        logger.debug(f"[SettingsCache] HIT — {len(result)} keys for company {company_id}")
        return result


    settings = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == company_id)
    ).all()
    result = {
        item.key: decrypt_value(item.value) if item.is_secret else item.value
        for item in settings
    }

    # Populate cache (sentinel marks the company as loaded, even if settings are empty)
    _sc.update({_SETTINGS_CACHE_SENTINEL: "1", **result}, user_id=company_id)
    logger.info(f"[SettingsCache] MISS — loaded {len(result)} keys for company {company_id} into cache")
    return result


def _resolve_setting(settings: dict[str, str], keys: list[str], hint: str):
    for key in keys:
        normalized_key = key.upper()
        value = settings.get(normalized_key) or settings.get(key)
        if value:
            logger.info(f"[Settings] {hint} resolved from company_settings.{normalized_key}")
            return value

    for key in keys:
        normalized_key = key.upper()
        env_value = os.getenv(normalized_key)
        if env_value:
            logger.info(f"[EnvVar] {hint} resolved from ${normalized_key}")
            return env_value

    logger.info(f"[Fallback] {hint} not found in company_settings or env")
    return None


class VoicePipeline:
    def __init__(self, communicator, interaction_id: str, system_prompt: str, transcript_accumulator: List[str], session: Session,
                 stt_provider: str = "deepgram", llm_provider: str = "mistral", tts_provider: str = "cartesia",
                 company_name: str = "Yexis Electronics", user: User = None, lead_context: str = None,
                 company_website: str = None, lead_id: int = None,
                 audio_encoding: str = "pcm_mulaw", audio_sample_rate: int = 8000,
                 lead_language: str = "en-IN", runtime_json: dict = None, agent_id: int | None = None):
        self.communicator = communicator
        self.interaction_id = interaction_id
        self.system_prompt = system_prompt
        self.transcript_accumulator = transcript_accumulator
        self._transcript_dirty = False
        self.session = session
        self.company_name = company_name
        self.user = user
        self.lead_context = lead_context
        self.company_website = company_website
        user_id = user.id if user else None
        self.user_id = user_id
        self.lead_id = lead_id
        self.company_id = user.company_id if user else None
        self._call_sid: str | None = None
        self.lead_timezone = os.getenv("DEFAULT_TIMEZONE", "Asia/Kolkata")

        company_id = user.company_id if user else None
        all_settings = _load_company_settings(session, company_id)

        self.stt_provider = stt_provider or "deepgram"
        self.llm_provider = llm_provider or "mistral"
        self.tts_provider = tts_provider or "cartesia"
        self.lead_language = lead_language or "en-IN"
        self.agent_id = agent_id

        self.audio_encoding = audio_encoding
        self.audio_sample_rate = audio_sample_rate
        self.last_customer_speech_time = time.time()
        self.last_rio_speech_end_time = time.time()
        
        # Basic Initialization (Core loop attributes)
        self.sentence_queue = asyncio.Queue()
        self.current_tts_task = None
        self.current_llm_task = None
        self.is_rio_speaking = False
        self.tts_first_byte_time = 0.0
        self.last_tts_start_time = 0.0
        self.llm_error_count = 0 
        self.current_turn_user_text = ""
        self.pending_user_turn_text = ""
        self.pending_llm_latency = 0.0
        self.llm_dispatch_task: asyncio.Task | None = None
        self._pending_tts_fallback_task: asyncio.Task | None = None
        self.post_stt_grace = 1.5
        self.interrupt_pending = False
        self.pause_playback = False
        self.resume_event = asyncio.Event()
        self.resume_event.set()
        self.pending_interrupt_reason: str | None = None
        self.last_rio_sentences: deque[str] = deque(maxlen=3)
        self._last_clear_ts = 0.0

        # Barge-in tuning — runtime_json (per-agent) > env > hardcoded default.
        _bi = (runtime_json or {}).get("barge_in", {})
        self.barge_rms_threshold = int(_bi.get("rms_threshold") or os.getenv("BARGE_RMS_THRESHOLD", "1200"))
        self.barge_frames_needed = int(_bi.get("frames_needed") or os.getenv("BARGE_FRAMES_NEEDED", "8"))
        self.barge_silence_reset_frames = int(_bi.get("silence_reset_frames") or os.getenv("BARGE_SILENCE_RESET_FRAMES", "20"))
        self.barge_tts_guard_ms = int(_bi.get("tts_guard_ms") or os.getenv("BARGE_TTS_GUARD_MS", "1500"))
        self.barge_post_speech_cooldown_ms = int(_bi.get("post_speech_cooldown_ms") or os.getenv("BARGE_POST_SPEECH_COOLDOWN_MS", "1200"))
        self.barge_clear_cooldown_ms = int(_bi.get("clear_cooldown_ms") or os.getenv("BARGE_CLEAR_COOLDOWN_MS", "600"))
        self.barge_retrigger_cooldown_ms = int(_bi.get("retrigger_cooldown_ms") or os.getenv("BARGE_RETRIGGER_COOLDOWN_MS", "2500"))
        _bi_disabled = _bi.get("disabled")
        self.disable_barge_in = (
            (_bi_disabled is True or str(_bi_disabled).lower() in {"1", "true", "yes", "on"})
            if _bi_disabled is not None
            else os.getenv("DISABLE_BARGE_IN", "0").lower() in {"1", "true", "yes", "on"}
        )
        self._last_barge_trigger_ts = 0.0

        # Silero-VAD confirmation gate — opt-in via runtime_json or env.
        _bi_silero = _bi.get("use_silero_vad")
        self.use_silero_vad = (
            (_bi_silero is True or str(_bi_silero).lower() in {"1", "true", "yes", "on"})
            if _bi_silero is not None
            else os.getenv("USE_SILERO_VAD", "0").lower() in {"1", "true", "yes", "on"}
        )

        # Rolling buffer of sentences actually emitted to TTS this turn — used to seed the next LLM prompt with "you were saying X" context on confirmed barge-in, so the agent does not restart cold.
        self.last_rio_spoken: deque[str] = deque(maxlen=5)

        # End-of-call feedback enforcement: smaller LLMs sometimes drop the
        # rare "ask for 1-5 rating before goodbye" instruction.  We track
        # whether (a) Rio has actually asked, and (b) the customer has given
        # a 1-5 in their speech, so the speaker layer can force-prepend the
        # question if the LLM is about to say goodbye without having asked.
        self.feedback_asked_this_call = False
        self.user_gave_rating_this_call = False
        # Agent persona settings — customizable per company
        self.agent_name = (all_settings.get("AGENT_NAME") or "Rio").strip()
        self._agent_greeting_tpl = (all_settings.get("AGENT_GREETING") or "").strip()
        self._agent_greeting_personalized_tpl = (all_settings.get("AGENT_PERSONALIZED_GREETING") or "").strip()

        verbosity_level = str(all_settings.get("AI_VERBOSITY") or "2").strip()
        default_turn_caps = {"1": 2, "2": 4, "3": 6}
        self.max_sentences_per_turn = int(
            os.getenv("VOICE_MAX_SENTENCES_PER_TURN", str(default_turn_caps.get(verbosity_level, 4)))
        )
        self.max_sentences_per_turn = max(2, self.max_sentences_per_turn)
        self._sentences_emitted_this_turn = 0
        self.last_user_transcript = ""
        self.silence_reengage_count = 0

        # Azure uses distinct key names per service — resolve with provider-aware chains
        if self.llm_provider == "azure":
            llm_api_key = _resolve_setting(
                all_settings,
                ["AZURE_LLM_API_KEY", "AZURE_API_KEY", "LLM_API_KEY"],
                "Azure OpenAI LLM key",
            )
        else:
            llm_api_key = _resolve_setting(
                all_settings,
                [f"{self.llm_provider.upper()}_LLM_API_KEY", f"{self.llm_provider.upper()}_API_KEY", "LLM_API_KEY"],
                f"{self.llm_provider.upper()} LLM API key",
            )

        if self.tts_provider == "azure":
            tts_api_key = _resolve_setting(
                all_settings,
                ["AZURE_SPEECH_API_KEY", "AZURE_API_KEY", "TTS_API_KEY"],
                "Azure Speech TTS key",
            )
        elif self.tts_provider == "vachana":
            tts_api_key = _resolve_setting(
                all_settings,
                ["VACHANA_API_KEY", "GNANI_API_KEY", "TTS_API_KEY"],
                "Vachana/Gnani TTS API key",
            )
        else:
            tts_api_key = _resolve_setting(
                all_settings,
                [f"{self.tts_provider.upper()}_API_KEY", "TTS_API_KEY"],
                f"{self.tts_provider.upper()} TTS API key",
            )

        if self.stt_provider == "azure":
            stt_api_key = _resolve_setting(
                all_settings,
                ["AZURE_SPEECH_API_KEY", "AZURE_API_KEY", "STT_API_KEY"],
                "Azure Speech STT key",
            )
        elif self.stt_provider == "vachana":
            stt_api_key = _resolve_setting(
                all_settings,
                ["VACHANA_API_KEY", "GNANI_API_KEY", "STT_API_KEY"],
                "Vachana/Gnani STT API key",
            )
        else:
            stt_api_key = _resolve_setting(
                all_settings,
                [f"{self.stt_provider.upper()}_API_KEY", "STT_API_KEY"],
                f"{self.stt_provider.upper()} STT API key",
            )

        llm_model = _resolve_setting(
            all_settings,
            [f"{self.llm_provider.upper()}_LLM_MODEL", f"{self.llm_provider.upper()}_MODEL", "LLM_MODEL"],
            f"{self.llm_provider.upper()} LLM model",
        )
        tts_voice = _resolve_setting(
            all_settings,
            [
                f"{self.tts_provider.upper()}_TTS_VOICE",
                f"{self.tts_provider.upper()}_VOICE_ID",
                f"{self.tts_provider.upper()}_VOICE",
                "TTS_VOICE_ID",
            ],
            f"{self.tts_provider.upper()} TTS voice",
        )
        tts_model = _resolve_setting(
            all_settings,
            [
                f"{self.tts_provider.upper()}_TTS_MODEL",
                f"{self.tts_provider.upper()}_MODEL",
                "TTS_MODEL",
            ],
            f"{self.tts_provider.upper()} TTS model",
        )
        stt_model = _resolve_setting(
            all_settings,
            [
                f"{self.stt_provider.upper()}_STT_MODEL",
                f"{self.stt_provider.upper()}_MODEL",
                "STT_MODEL",
            ],
            f"{self.stt_provider.upper()} STT model",
        )

        if self.lead_id:
            try:
                lead = self.session.get(Lead, self.lead_id)
                self.lead_timezone = resolve_lead_timezone(
                    lead,
                    session=self.session,
                    company_id=self.company_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to load lead context for interaction %s: %s",
                    self.interaction_id,
                    str(e),
                    extra={"lead_id": lead_id}
                )
        time_context = self._build_time_context()
        
        full_system_prompt = system_prompt + time_context
        self.llm_service = get_llm_service(self.llm_provider, full_system_prompt, api_key=llm_api_key, model=llm_model)
        self.tts_service = get_tts_service(self.tts_provider, api_key=tts_api_key, voice_id=tts_voice, model=tts_model)
        self.stt_service = get_stt_service(self.stt_provider, api_key=stt_api_key, model=stt_model)

        # Azure needs region + endpoint injected post-construction (not in factory signature)
        if self.tts_provider == "azure":
            _az_speech_region = (
                all_settings.get("AZURE_SPEECH_REGION")
                or os.getenv("AZURE_SPEECH_REGION", "eastus")
            )
            self.tts_service.region = _az_speech_region
            self.tts_service.base_url = (
                f"https://{_az_speech_region}.tts.speech.microsoft.com/cognitiveservices/v1"
            )
            if tts_api_key:
                self.tts_service.api_key = tts_api_key
            logger.info("[Pipeline] Azure TTS region=%s voice=%s", _az_speech_region, tts_voice)

        if self.stt_provider == "azure":
            _az_speech_region = (
                all_settings.get("AZURE_SPEECH_REGION")
                or os.getenv("AZURE_SPEECH_REGION", "eastus")
            )
            self.stt_service.region = _az_speech_region
            if stt_api_key:
                self.stt_service.api_key = stt_api_key
            logger.info("[Pipeline] Azure STT region=%s lang=%s", _az_speech_region, stt_model)

        if self.llm_provider == "azure":
            _az_llm_endpoint = (
                all_settings.get("AZURE_LLM_ENDPOINT")
                or os.getenv("AZURE_OPENAI_ENDPOINT", "")
            )
            _az_llm_version = (
                all_settings.get("AZURE_LLM_API_VERSION")
                or os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
            )
            self.llm_service.endpoint = _az_llm_endpoint
            self.llm_service.api_version = _az_llm_version
            if _az_llm_endpoint and llm_api_key:
                try:
                    from openai import AsyncAzureOpenAI as _AzureOAI
                    self.llm_service.client = _AzureOAI(
                        api_key=llm_api_key,
                        azure_endpoint=_az_llm_endpoint,
                        api_version=_az_llm_version,
                    )
                    logger.info("[Pipeline] Azure LLM client initialized endpoint=%s", _az_llm_endpoint)
                except Exception as _e:
                    logger.error("[Pipeline] Azure LLM client init failed: %s", _e)

        # Circuit breakers — wrap STT/LLM/TTS with resilience + fallback chains
        from services.voice.circuit_breaker import CircuitBreaker
        self._stt_cb = CircuitBreaker("stt", threshold=3, recovery_s=30)
        self._llm_cb = CircuitBreaker("llm", threshold=3, recovery_s=15)
        self._tts_cb = CircuitBreaker("tts", threshold=5, recovery_s=30)

        # Inject language into Sarvam services when a non-default language is active
        if self.lead_language and self.lead_language != "en-IN":
            if hasattr(self.stt_service, "language"):
                _stt_lang = self.lead_language[0] if isinstance(self.lead_language, list) else str(self.lead_language)
                self.stt_service.language = _stt_lang
                logger.info("[Pipeline] STT language set to %s", _stt_lang)
            if hasattr(self.tts_service, "target_language_code"):
                self.tts_service.target_language_code = self.lead_language
                logger.info("[Pipeline] Sarvam TTS language set to %s", self.lead_language)

        # Store keys globally on instance for reference if needed
        self.integration_keys = all_settings

        # Inject pre-fetched lead/prospect context if provided at start
        if lead_context:
            self._apply_context_to_prompt(lead_context)

        # Inject objection playbook from the company library
        if company_id:
            try:
                from services.objection_service import get_objection_playbook
                playbook = get_objection_playbook(session, company_id)
                if playbook:
                    current_prompt = self.llm_service.system_prompt
                    self.llm_service.update_system_prompt(current_prompt + playbook)
                    logger.info("[Pipeline] Objection playbook injected (%d entries)", playbook.count("→"))
            except Exception as _pe:
                logger.debug("[Pipeline] Objection playbook skipped: %s", _pe)

        self.last_context_type = "general"

        # Trace context — one trace_id per call, turn_index increments each turn
        self.trace_id = _uuid.uuid4().hex
        self.turn_index = 0
        
        # Initialize handlers (Phase 3 refactoring)
        self.stt_handler = STTHandler(
            stt_service=self.stt_service,
            communicator=self.communicator,
            audio_encoding=self.audio_encoding,
            audio_sample_rate=self.audio_sample_rate
        )
        
        self.tts_handler = TTSHandler(
            tts_service=self.tts_service,
            communicator=self.communicator
        )
        
        self.llm_handler = LLMHandler(
            llm_service=self.llm_service,
            max_sentences_per_turn=self.max_sentences_per_turn
        )
        
        self.interrupt_manager = InterruptManager(
            rms_threshold=self.barge_rms_threshold,
            frames_needed=self.barge_frames_needed,
            silence_reset_frames=self.barge_silence_reset_frames,
            tts_guard_ms=self.barge_tts_guard_ms,
            post_speech_cooldown_ms=self.barge_post_speech_cooldown_ms,
            clear_cooldown_ms=self.barge_clear_cooldown_ms,
            retrigger_cooldown_ms=self.barge_retrigger_cooldown_ms,
            use_silero_vad=self.use_silero_vad,
            disabled=self.disable_barge_in
        )
        
        self.transcript_manager = TranscriptManager(
            interaction_id=self.interaction_id,
            session=self.session
        )

        # ── Graph Agent Engine (Phase 1: graph-based conversation flows) ──
        self.runtime_json = runtime_json or {}
        # Per-agent feedback phrase (overrides class-level constant)
        self._feedback_phrase = self.runtime_json.get("feedback_phrase") or self._FORCED_FEEDBACK_PHRASE
        self.graph_engine = create_graph_engine_from_runtime(
            runtime_json=self.runtime_json,
            llm_service=self.llm_service,
            rag_service=None,
            tool_executor=execute_mcp_tool,
            routing_llm_callable=None,
        )
        if self.graph_engine and self.graph_engine.is_graph_agent:
            logger.info(
                "[Pipeline] Graph agent engine enabled: %d nodes, starting at '%s'",
                len(self.graph_engine.config.nodes),
                self.graph_engine.current_node_id,
            )

        # ── Voicemail Detection (Phase 1) ──
        vm_config = self.runtime_json.get("voicemail", {})
        # Enable if set in runtime_json OR in company settings key VOICEMAIL_DETECTION_ENABLED
        _vm_setting = (all_settings.get("VOICEMAIL_DETECTION_ENABLED") or "").lower()
        _vm_enabled = vm_config.get("enabled", False) or _vm_setting in ("1", "true", "yes", "on")
        self.voicemail_handler = VoicemailHandler(
            llm_service=self.llm_service,
            enabled=_vm_enabled,
            detection_duration=int(vm_config.get("detection_duration") or all_settings.get("VOICEMAIL_DETECTION_DURATION") or 30),
            check_interval=int(vm_config.get("check_interval") or 7),
            min_transcript_length=int(vm_config.get("min_transcript_length") or 7),
        )
        if _vm_enabled:
            logger.info("[Pipeline] Voicemail detection enabled")

        # ── Phase 2: Language Detection & Auto-Switching ──
        lang_config = self.runtime_json.get("language_detection", {})
        self.language_detector = LanguageDetector(
            llm_service=self.llm_service,
            lid_provider=lang_config.get("provider", "llm"),
            lid_api_key=lang_config.get("api_key"),
            detection_turns=lang_config.get("detection_turns", 3),
            enabled=lang_config.get("enabled", False),
            supported_languages=lang_config.get("supported_languages"),
        )
        if lang_config.get("enabled"):
            logger.info("[Pipeline] Language detection enabled")

        # ── Phase 2: Filler & Backchanneling ──
        filler_config = self.runtime_json.get("filler", {})
        self.filler_service = FillerService(
            use_fillers=filler_config.get("use_fillers", False),
            backchanneling_enabled=filler_config.get("backchanneling", False),
            backchanneling_message_gap=filler_config.get("backchanneling_message_gap", 5.0),
            backchanneling_start_delay=filler_config.get("backchanneling_start_delay", 5.0),
        )
        if filler_config.get("use_fillers") or filler_config.get("backchanneling"):
            logger.info("[Pipeline] Filler/backchanneling enabled")

        # ── Phase 2: Ambient Noise ──
        noise_config = (
            self.runtime_json.get("ambient_noise")
            or (self.runtime_json.get("call_features") or {}).get("ambient_noise")
            or None
        )
        if not noise_config:
            # Fall back to company-wide settings
            _an_enabled = all_settings.get("AMBIENT_NOISE_ENABLED") or all_settings.get("ambient_noise_enabled")
            if _an_enabled == "1":
                noise_config = {
                    "enabled": True,
                    "preset": all_settings.get("AMBIENT_NOISE_PRESET") or all_settings.get("ambient_noise_preset") or "call-center",
                    "volume": float(all_settings.get("AMBIENT_NOISE_VOLUME") or all_settings.get("ambient_noise_volume") or "0.15") / 100,
                }
            else:
                noise_config = {}
        _provider_ok = isinstance(self.communicator, (PlivoCommunicator, VobizCommunicator))
        if noise_config.get("enabled") and not _provider_ok:
            logger.info(
                "[Pipeline] Ambient noise disabled: provider %s not supported (Plivo/Vobiz only)",
                type(self.communicator).__name__,
            )
        self.ambient_noise_service = AmbientNoiseService(
            preset=noise_config.get("preset", "call-center"),
            volume=noise_config.get("volume", 0.15),
            enabled=noise_config.get("enabled", False) and _provider_ok,
        )
        if self.ambient_noise_service.enabled:
            logger.info(
                "[Pipeline] Ambient noise enabled: %s @ %.0f%%",
                noise_config.get("preset", "call-center"),
                noise_config.get("volume", 0.15) * 100,
            )
            # Wrap communicator.send_media to mix ambient noise into every TTS chunk.
            # All TTS providers emit base64-encoded mulaw; we decode → mix → re-encode.
            _noise_svc = self.ambient_noise_service
            _orig_send_media = self.communicator.send_media

            async def _noisy_send_media(audio_data):
                if _noise_svc.enabled and audio_data:
                    try:
                        raw = base64.b64decode(audio_data)
                        pcm = audioop.ulaw2lin(raw, 2)
                        pcm = _noise_svc.mix_bytes(pcm, sample_width=2)
                        mulaw = audioop.lin2ulaw(pcm, 2)
                        audio_data = base64.b64encode(mulaw).decode()
                    except Exception as _exc:
                        logger.debug("[AmbientNoise] Mix skipped: %s", _exc)
                await _orig_send_media(audio_data)

            self.communicator.send_media = _noisy_send_media

        # ── Phase 3: Final Call Message (per-language, played before hangup) ──
        cf_config = self.runtime_json.get("call_features", {})
        self.final_call_message: dict[str, str] = cf_config.get("final_call_message", {}) or {}
        self.final_call_message_lang_map: dict[str, str] = {}
        for lang_code, msg in self.final_call_message.items():
            if msg and msg.strip():
                self.final_call_message_lang_map[lang_code] = msg.strip()

        # ── DTMF in-call keypad routing ──
        _dtmf_cfg = cf_config.get("dtmf") or {}
        self.dtmf_enabled: bool = bool(_dtmf_cfg.get("enabled", False))
        self.dtmf_menu: dict = _dtmf_cfg.get("menu", {}) or {}

        # ── Phase 3: Per-agent retry config ──
        self.retry_config: dict = self.runtime_json.get("retry", {}) or {}

    def _silero_confirms(self, audio_chunk: bytes) -> bool:
        """Wrap Silero VAD with the same encoding the barge-in loop receives.

        Fails OPEN — any exception returns True so a misbehaving VAD never
        silently drops legitimate barge-ins.  Call only when `use_silero_vad`
        is set; RMS stays as the cheap first-pass filter.
        """
        try:
            from services.ai.vad import silero_confirms_speech
            return silero_confirms_speech(
                audio_bytes=audio_chunk,
                encoding=self.audio_encoding,
                sample_rate=self.audio_sample_rate,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[VoicePipeline] Silero gate failure (fail-open): %s", exc)
            return True

    def _pause_playback_for_interrupt(self):
        if not self.pause_playback:
            self.pause_playback = True
            self.resume_event.clear()

    def _resume_playback_from_interrupt(self):
        if self.pause_playback:
            self.pause_playback = False
            self.resume_event.set()

    def _clear_sentence_queue(self):
        while not self.sentence_queue.empty():
            try:
                self.sentence_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

    def _cancel_pending_llm_dispatch(self):
        if self.llm_dispatch_task and not self.llm_dispatch_task.done():
            self.llm_dispatch_task.cancel()
        self.llm_dispatch_task = None

    def _compute_grace(self, transcript: str) -> float:
        """Adaptive grace period based on utterance characteristics.

        Short questions need almost no grace — the user is clearly done speaking.
        Long complex utterances get a bit more room for trailing words.
        """
        if hasattr(self, "post_stt_grace") and self.post_stt_grace <= 0.1:
            return self.post_stt_grace

        t = transcript.rstrip()
        words = len(t.split())
        if t.endswith("?"):      return 0.10
        if words <= 4:           return 0.15
        if words <= 10:          return 0.25
        return float(os.getenv("POST_STT_GRACE_S", "0.35"))

    def _schedule_llm_dispatch(self, latency: float):
        self.pending_llm_latency = latency
        self._cancel_pending_llm_dispatch()
        if not self.pending_user_turn_text.strip():
            return
        self.llm_dispatch_task = asyncio.create_task(self._defer_llm_dispatch())

    async def _defer_llm_dispatch(self):
        try:
            transcript_for_grace = self.pending_user_turn_text.strip()
            grace = self._compute_grace(transcript_for_grace)
            await asyncio.sleep(grace)
            if self.interrupt_pending:
                return
            transcript = self.pending_user_turn_text.strip()
            self.pending_user_turn_text = ""
            if not transcript:
                return

            # Play an immediate acknowledgment filler so the user hears something
            # within ~300ms while the LLM generates its real response.
            try:
                lang = (getattr(self, "lead_language", "") or "en")[:2]
                ack = self.filler_service.get_tool_filler("thinking", language=lang)
                if ack and self.sentence_queue.empty() and not self.is_rio_speaking:
                    await self.sentence_queue.put((ack, True))
                    await asyncio.sleep(0.05)
                # Silently refill LLM pool if running low
                asyncio.create_task(
                    self.filler_service._maybe_refill(self.llm_service),
                    name="filler_pool_refill",
                )
            except Exception:  # noqa: BLE001
                pass

            await self._dispatch_llm(transcript, self.pending_llm_latency)
        except asyncio.CancelledError:
            return
        finally:
            self.llm_dispatch_task = None

    async def _dispatch_llm(self, transcript: str, latency: float, interrupted_context: str = ""):
        if not transcript:
            return
        fast_path = self._get_fast_path_response(transcript)
        if fast_path:
            self._sentences_emitted_this_turn = 0
            self.transcript_manager.add_rio_turn(fast_path)
            # Mirror into the pipeline's accumulator for backward compatibility
            self.transcript_accumulator.append(f"Rio: {fast_path}")
            self.save_transcript()
            await self.sentence_queue.put((fast_path, True))
            return
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
        # Inject "you were saying X" context ONCE before the user turn lands. Must fire before _process_llm_response adds the user message.
        if interrupted_context:
            try:
                self.llm_service.add_system_message(
                    "[MID-TURN INTERRUPTION]\n"
                    f"You were just saying: \"{interrupted_context}\"\n"
                    f"The user cut you off to say: \"{transcript}\"\n"
                    "Acknowledge their interruption and address what they said. "
                    "Do NOT repeat what you already said."
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[VoicePipeline] add_system_message for interrupt failed: %s", exc)
        turn_guidance = self._build_turn_guidance(transcript)
        if turn_guidance:
            try:
                self.llm_service.add_system_message(turn_guidance)
            except Exception as exc:  # noqa: BLE001
                logger.warning("[VoicePipeline] add_system_message for turn guidance failed: %s", exc)
        self.current_llm_task = asyncio.create_task(
            self._process_llm_response(transcript, latency)
        )

    def _handle_false_positive_interrupt(self):
        logger.info("⏹️ False positive interruption detected. Resuming playback.")
        self.interrupt_pending = False
        self.pending_interrupt_reason = None
        self._resume_playback_from_interrupt()

    def _handle_confirmed_interrupt(self, latency: float):
        logger.info("🔄 Confirmed interruption. Restarting inference with accumulated transcripts.")
        self.interrupt_pending = False
        self.pending_interrupt_reason = None
        self._cancel_pending_llm_dispatch()
        self._clear_sentence_queue()
        if self.current_tts_task and not self.current_tts_task.done():
            self.current_tts_task.cancel()
        if self.current_llm_task and not self.current_llm_task.done():
            self.current_llm_task.cancel()
        transcript = self.pending_user_turn_text.strip()
        self.pending_user_turn_text = ""
        # Snapshot + clear the "what we had actually said this turn" buffer so the next LLM call can acknowledge the interruption.  Next turn starts with a fresh buffer.
        interrupted_text = " ".join(s for s in self.last_rio_spoken if s).strip()
        self.last_rio_spoken.clear()
        self._resume_playback_from_interrupt()
        if transcript:
            asyncio.create_task(
                self._dispatch_llm(transcript, latency, interrupted_context=interrupted_text)
            )

    def _apply_context_to_prompt(self, context: str):
        """Helper to structure and inject lead context into the LLM service."""
        prospect_context = (
            f"\n\n### [PROSPECT BACKGROUND]\n"
            f"You are ALREADY speaking to an IDENTIFIED prospect. Here is their comprehensive record:\n\n"
            f"{context}\n"
            f"--- \n"
            f"CRITICAL SALES INSTRUCTIONS:\n"
            f"1. Use only the numeric `[__META_ID__]` for backend tool calls. Do NOT mention this ID in speech.\n"
            f"2. You are 'Rio', a helpful human representative. NEVER say you have a 'record', 'lead info', or 'ID' for them.\n"
            f"3. Greet them by name naturally (e.g., 'Hi Lokesh'). Do NOT report what you know about them.\n"
            f"4. Focus on the value of our products and solving their needs, not database operations."
        )
        
        # Re-build full system prompt
        time_context = self._build_time_context()

        full_system_prompt = self.system_prompt + time_context + prospect_context
        # Ensure llm_service is already initialized before calling this
        if hasattr(self, 'llm_service') and self.llm_service:
            self.llm_service.update_system_prompt(full_system_prompt)
        self.lead_context = context
        logger.info(f"📋 [Pipeline] Assertive lead context injected into system prompt")

    def _build_time_context(self) -> str:
        localized_now = format_datetime_for_timezone(
            datetime.now(),
            self.lead_timezone,
            include_timezone=True,
        )
        return (
            "\n\n[SYSTEM CONTEXT]: "
            f"The lead's local timezone is {self.lead_timezone}. "
            f"The current local time for this lead is {localized_now}. "
            "Use this local timezone to resolve relative dates like 'tomorrow' or "
            "'next Tuesday' into ISO strings for tool calls. When speaking about "
            "appointments, confirmations, reminders, or reschedules, always say the "
            "time in the lead's local timezone unless the customer explicitly asks for another timezone."
        )

    def _normalize_text(self, text: str | None) -> str:
        if not text:
            return ""
        return re.sub(r"[^a-z0-9\s]", "", text.lower()).strip()

    # Forced end-of-call feedback enforcement helpers.
    _RATING_IN_USER_RE = re.compile(
        r"\b(rat(?:e|ed|ing)|i(?:'d|'ll| would| will)?\s+say|give|out\s+of\s+(?:5|five)|stars?)\b[^.!?]{0,30}?\b(one|two|three|four|five|[1-5])\b",
        re.IGNORECASE,
    )
    _GOODBYE_RE = re.compile(
        r"\b(goodbye|good\s*bye|bye(?:\s*bye)?|take\s+care|have\s+a\s+(?:great|wonderful|good|nice)\s+day|"
        r"talk\s+to\s+you\s+(?:soon|later)|see\s+you\s+(?:soon|later)|wrap\s+up|thanks\s+for\s+chatting)\b",
        re.IGNORECASE,
    )
    _FEEDBACK_ASK_RE = re.compile(
        r"(scale\s+of\s+1\s+to\s+5|rate\s+your\s+experience|how\s+would\s+you\s+rate)",
        re.IGNORECASE,
    )
    _AUDIBILITY_RE = re.compile(
        r"\b(am i audible|can you hear me|are you able to hear me|are you there|hello what happened|can you hear this)\b",
        re.IGNORECASE,
    )
    _TOPIC_SWITCH_RE = re.compile(
        r"\b(move on|other product|another product|switch product|different product|get to the point|skip that|not that one)\b",
        re.IGNORECASE,
    )
    _DETAIL_REQUEST_RE = re.compile(
        r"\b(compare|comparison|details|specs|specifications|features|pricing|price|availability|options)\b",
        re.IGNORECASE,
    )
    _DETAIL_FOLLOWUP_RE = re.compile(
        r"\b(more details|go deeper|tell me more|later one|latter one|second one|that one|the other one)\b",
        re.IGNORECASE,
    )
    _ACTIVE_REQUEST_RE = re.compile(
        r"\b(compare|comparison|details|specs|features|pricing|price|availability|share|send|email|whatsapp|options|tell me more|go deeper|other product|another product)\b",
        re.IGNORECASE,
    )
    _OFF_TOPIC_RE = re.compile(
        r"\b(pizza|peaceout|peace out|public set channel)\b",
        re.IGNORECASE,
    )
    _FORCED_FEEDBACK_PHRASE = (
        "Before we wrap up — on a scale of 1 to 5, how would you rate your experience speaking with me today?"
    )

    def _customer_uttered_rating(self, transcript: str) -> bool:
        return bool(transcript and self._RATING_IN_USER_RE.search(transcript))

    def _sentence_says_goodbye(self, sentence: str) -> bool:
        return bool(sentence and self._GOODBYE_RE.search(sentence))

    def _sentence_asks_feedback(self, sentence: str) -> bool:
        return bool(sentence and self._FEEDBACK_ASK_RE.search(sentence))

    def _should_defer_feedback(self) -> bool:
        if self.user_gave_rating_this_call:
            return False
        transcript = (self.last_user_transcript or "").strip()
        if not transcript:
            return False
        return bool(self._ACTIVE_REQUEST_RE.search(transcript))

    def _get_fast_path_response(self, transcript: str) -> str | None:
        if not transcript:
            return None
        if self._AUDIBILITY_RE.search(transcript):
            return "Yes, I can hear you. I'm here with you."
        return None

    def _build_turn_guidance(self, transcript: str) -> str | None:
        notes: list[str] = []
        if self._TOPIC_SWITCH_RE.search(transcript):
            notes.append(
                "The customer is redirecting the conversation. Acknowledge the switch briefly and do not repeat the previous product summary."
            )
        if self._DETAIL_REQUEST_RE.search(transcript):
            notes.append(
                "If you provide product details, comparisons, pricing, or specs, use get_product_info first instead of answering from memory."
            )
        if self._DETAIL_FOLLOWUP_RE.search(transcript):
            notes.append(
                "The customer is asking for follow-up detail on an already-mentioned option. Do not ask a broad reset question if the referent is reasonably clear."
            )
        if self._OFF_TOPIC_RE.search(transcript):
            notes.append(
                "Do not mirror jokes or slang. Reply professionally and steer back to the active sales task."
            )
        if not notes:
            return None
        return "[TURN GUIDANCE]\n" + "\n".join(f"- {note}" for note in notes)

    def _tool_followup_phrase(self, tool_name: str, result: dict[str, Any]) -> str | None:
        if not isinstance(result, dict):
            return None
        if tool_name == "send_communication":
            status = result.get("channel_status") or {}
            queued = [k for k, v in status.items() if v == "queued"]
            sent = [k for k, v in status.items() if v == "sent"]
            failed = [k for k, v in status.items() if v == "failed"]
            parts: list[str] = []
            if queued:
                parts.append(f"I've queued the {', '.join(queued)}.")
            if sent:
                parts.append(f"I've sent the {', '.join(sent)}.")
            if failed:
                parts.append(f"I couldn't send the {', '.join(failed)} just yet.")
            return " ".join(parts) if parts else "I couldn't send that just yet."
        if tool_name in {"book_meeting", "book_demo"}:
            if result.get("confirmed") or result.get("success"):
                if result.get("duplicate"):
                    return "You already have that scheduled."
                return "I've got that scheduled."
            return None
        return None

    def _tool_followup_note(self, phrase: str) -> str:
        return (
            "[TOOL RESULT SPEECH]\n"
            f"You have already told the customer: \"{phrase}\"\n"
            "Do not repeat or embellish that confirmation. Continue only with the next useful step."
        )

    def _is_low_value_fragment(self, text: str) -> bool:
        if not text:
            return True
        trimmed = text.strip().strip('"').strip("'").strip()
        if not trimmed:
            return True
        words = trimmed.split()
        if len(words) == 1 and trimmed.lower() in {"so", "right", "okay", "great", "lokesh", "hello"}:
            return True
        if len(words) <= 2 and trimmed.endswith(","):
            return True
        if (text.strip().startswith('"') or text.strip().startswith("'")) and len(words) <= 6 and not re.search(r"[.?!]$", trimmed):
            return True
        if len(words) <= 3 and not re.search(r"[.?!]$", trimmed) and trimmed.lower() in {
            "just to confirm",
            "sending that over",
            "let me see",
            "one moment",
        }:
            return True
        return False

    def _is_echo_transcript(self, transcript: str) -> bool:
        normalized = self._normalize_text(transcript)
        if not normalized:
            return False
        for sentence in self.last_rio_sentences:
            candidate = self._normalize_text(sentence)
            if not candidate:
                continue
            if normalized == candidate or candidate.startswith(normalized) or normalized.startswith(candidate):
                return True
        return False

    async def _load_lead_context(self, lead_id: int):
        """Load lead context from DB + pre-call KB cache and inject into system prompt."""
        if not lead_id or lead_id <= 0:
            return

        logger.info(f"🔍 [Pipeline] Loading context for Lead #{lead_id}...")

        try:
            lead = self.session.get(Lead, lead_id)
            self.lead_timezone = resolve_lead_timezone(
                lead,
                session=self.session,
                company_id=self.company_id,
            )
        except Exception as exc:
            logger.debug("[Pipeline] Lead timezone resolution failed (non-blocking): %s", exc)

        
        context = get_comprehensive_lead_context(self.session, lead_id)
        if context:
            self._apply_context_to_prompt(context)

        # Pre-call KB context (products, objections, competitors) from orchestrator cache
        try:
            from utils.precall_cache import get as cache_get, format_kb_context_for_prompt, evict
            company_id = self.company_id
            if company_id:
                cached = cache_get(company_id, lead_id)
                if cached:
                    kb_text = format_kb_context_for_prompt(cached)
                    if kb_text and hasattr(self, "llm_service") and self.llm_service:
                        current = self.llm_service.system_prompt
                        self.llm_service.update_system_prompt(current + kb_text)
                        logger.info(
                            "📚 [Pipeline] KB context injected (%d chunks) for lead %s",
                            len(cached.get("kb_context", [])),
                            lead_id,
                        )
                    # Inject ICP score hint for routing decisions
                    icp = cached.get("icp_score", 0.0)
                    if icp >= 0.75 and hasattr(self, "llm_service") and self.llm_service:
                        current = self.llm_service.system_prompt
                        icp_hint = (
                            f"\n\n[ICP SIGNAL] This lead has a high fit score ({icp:.0%}). "
                            "Prioritise demo booking and closing language."
                        )
                        self.llm_service.update_system_prompt(current + icp_hint)
                    evict(company_id, lead_id)
        except Exception as exc:
            logger.debug("[Pipeline] Pre-call cache read failed (non-blocking): %s", exc)

    async def run(self):
        speaker_task = asyncio.create_task(self._speaker_loop())
        silence_task = asyncio.create_task(self._silence_watcher())
        audio_queue = asyncio.Queue()

        async def _ingest():
            async for data in self.communicator.receive():
                if data.get("event") == "dtmf" and self.dtmf_enabled:
                    digit = (data.get("dtmf") or {}).get("digit") or data.get("digit", "")
                    if digit:
                        asyncio.create_task(self._handle_dtmf(str(digit)))
                else:
                    await audio_queue.put(data)
            await audio_queue.put({"event": "stop"})

        ingest_task = asyncio.create_task(_ingest())

        logger.info("⏳ Waiting for telephony stream to start...")
        try:
            while True:
                data = await asyncio.wait_for(audio_queue.get(), timeout=15.0)
                if data.get("event") == "start":
                    start_msg = data.get("start", {})
                    self.communicator.stream_sid = start_msg.get("streamSid") or start_msg.get("streamId")
                    call_sid = start_msg.get("callSid")
                    if call_sid:
                        self._call_sid = call_sid

                    # Proactively check for lead_id/interaction_id in start parameters (Twilio specific)
                    params = start_msg.get("customParameters", {})
                    stream_lead_id = params.get("lead_id")
                    stream_int_id = params.get("interaction_id")
                    
                    if stream_lead_id:
                        try:
                            lid = int(stream_lead_id)
                            # Only load if we don't already have context
                            if not self.lead_context:
                                await self._load_lead_context(lid)
                        except (ValueError, TypeError):
                            pass
                            
                    # Only adopt stream-supplied interaction_id when we don't already have one from main.py's pre-validated session. An attacker-controlled or stale stream parameter could otherwise re-attach transcript writes to a different DB row, splitting a single call across records.
                    if stream_int_id and not self.interaction_id:
                        self.interaction_id = stream_int_id
                    elif stream_int_id and str(stream_int_id) != str(self.interaction_id):
                        logger.warning(
                            "[Pipeline] stream_int_id=%s differs from session interaction_id=%s — keeping session value",
                            stream_int_id, self.interaction_id,
                        )

                    logger.info(f"🚀 [Telephony] Stream started. Sid: {self.communicator.stream_sid} | Interaction: {self.interaction_id}")
                    break
                elif data.get("event") == "stop":
                    logger.error("❌ Got stop before start. Exiting.")
                    return
        except asyncio.TimeoutError:
            logger.error("❌ Timed out waiting for start event.")
            return

        # Personalized greeting if lead context is available
        _default_greeting = f"Hello, I'm {self.agent_name} from {self.company_name}. How are you doing today?"
        greeting = (
            self._agent_greeting_tpl
            .replace("{agent_name}", self.agent_name)
            .replace("{company_name}", self.company_name)
        ) if self._agent_greeting_tpl else _default_greeting

        if self.lead_context:
            try:
                name_line = [l for l in self.lead_context.split("\n") if "Name:" in l]
                if name_line:
                    lead_name = name_line[0].split(",")[0].replace("Name: ", "").replace("[PROSPECT DATA]", "").strip()
                    if lead_name and lead_name.lower() not in ["unknown", "n/a", "none"]:
                        if self._agent_greeting_personalized_tpl:
                            greeting = (
                                self._agent_greeting_personalized_tpl
                                .replace("{lead_name}", lead_name)
                                .replace("{agent_name}", self.agent_name)
                                .replace("{company_name}", self.company_name)
                            )
                        else:
                            greeting = f"Hello {lead_name}, this is {self.agent_name} from {self.company_name}. How are you doing today?"
                        logger.info(f"📞 [Personalized Greeting] Sent to {lead_name}")
            except Exception as e:
                logger.warning(f"⚠️ Failed to parse lead name for greeting: {e}")
        
        await self.sentence_queue.put((greeting, True))
        self.transcript_manager.add_rio_turn(greeting)
        # Mirror into the pipeline's accumulator for backward compatibility
        self.transcript_accumulator.append(f"Rio: {greeting}")
        self.save_transcript()

        # Pre-generate LLM filler pool while greeting plays (non-blocking)
        asyncio.create_task(
            self.filler_service.populate_llm_pool(self.llm_service),
            name="filler_pool_init",
        )

        # Register pipeline for event injection
        try:
            interaction_id_int = int(self.interaction_id)
            from services.voice.event_injection_service import register_pipeline
            register_pipeline(interaction_id_int, self)
        except (ValueError, TypeError):
            pass

        # Persist callSid so warm_transfer_service can find the live call
        if self._call_sid and self.interaction_id:
            try:
                from models.models import Interaction
                row = self.session.get(Interaction, int(self.interaction_id))
                if row:
                    meta = dict(row.metadata_json or {})
                    meta["call_sid"] = self._call_sid
                    row.metadata_json = meta
                    self.session.add(row)
                    self.session.commit()
            except Exception as _e:
                logger.warning("[Pipeline] Failed to persist call_sid: %s", _e)

        async def _audio_gen_from_queue():
            while True:
                data = await audio_queue.get()
                event = data.get("event")
                if event == "media":
                    yield base64.b64decode(data["media"]["payload"])
                elif event == "stop":
                    break

        # Two consumers of audio: barge-in detector + STT. We can't use the same generator twice, so we fan-out via a second queue.  The barge queue is bounded so a long call with DISABLE_BARGE_IN=1 (or a detector that briefly stalls) cannot grow it without limit. 200 chunks @ 20ms ≈ 4s of audio — plenty of headroom; OOM bound.
        stt_queue = asyncio.Queue()
        barge_queue: asyncio.Queue = asyncio.Queue(maxsize=200)

        async def _fan_out():
            """Read raw audio once, copy to both queues."""
            async for chunk in _audio_gen_from_queue():
                await stt_queue.put(chunk)
                # Drop-oldest on barge_queue to keep memory bounded when the detector lags (e.g., DISABLE_BARGE_IN=1).  STT side stays unbounded — losing STT audio would silently drop turns.
                try:
                    barge_queue.put_nowait(chunk)
                except asyncio.QueueFull:
                    try:
                        barge_queue.get_nowait()
                        barge_queue.put_nowait(chunk)
                    except Exception:  # noqa: BLE001
                        pass
            await stt_queue.put(None)   # sentinel
            try:
                barge_queue.put_nowait(None)
            except asyncio.QueueFull:
                # Drop one to make room for the sentinel.
                try:
                    barge_queue.get_nowait()
                    barge_queue.put_nowait(None)
                except Exception:  # noqa: BLE001
                    pass

        async def _stt_gen():
            """Feed STT from stt_queue."""
            while True:
                chunk = await stt_queue.get()
                if chunk is None:
                    break
                yield chunk

        async def _barge_in_detector():
            """
            Runs parallel to STT. Detects speech onset from raw mulaw audio.
            Uses RMS energy — no API, no latency. Fires the moment customer speaks.
            """
            import struct, math
            SPEECH_RMS = self.barge_rms_threshold
            SPEECH_FRAMES_NEEDED = self.barge_frames_needed
            SILENCE_RESET_FRAMES = self.barge_silence_reset_frames
            
            speech_counter = 0
            silence_counter = 0

            while True:
                if self.disable_barge_in:
                    await asyncio.sleep(0.05)
                    continue

                chunk = await barge_queue.get()
                if chunk is None:
                    break

                # mulaw → linear16 for RMS
                try:
                    pcm = audioop.ulaw2lin(chunk, 2)
                except Exception:
                    pcm = chunk

                samples = struct.unpack(f"<{len(pcm)//2}h", pcm)
                rms = math.sqrt(sum(s*s for s in samples) / len(samples)) if samples else 0

                now = time.time()

                # Guard: within TTS-start window (Rio just started speaking)
                tts_start_guard = (
                    self.is_rio_speaking
                    and self.last_tts_start_time > 0
                    and (now - self.last_tts_start_time) * 1000 < self.barge_tts_guard_ms
                )
                # Guard: post-speech cooldown — audio tail/echo after Rio finishes
                post_speech_guard = (
                    not self.is_rio_speaking
                    and self.last_rio_speech_end_time > 0
                    and (now - self.last_rio_speech_end_time) * 1000 < self.barge_post_speech_cooldown_ms
                )
                if tts_start_guard or post_speech_guard:
                    speech_counter = 0
                    continue

                if rms > SPEECH_RMS:
                    silence_counter = 0
                    speech_counter += 1
                    if speech_counter >= SPEECH_FRAMES_NEEDED:
                        if self.is_rio_speaking or not self.sentence_queue.empty():
                            # Rio is mid-speech — confirm with Silero before raising.
                            # RMS is cheap + catches silence; Silero is slow but rejects background noise / plosives / non-speech bursts.
                            if self.use_silero_vad and not self._silero_confirms(chunk):
                                logger.debug(f"🔕 [Barge-in] Silero rejected RMS spike (RMS:{rms:.0f}) — suppressing")
                                speech_counter = 0
                                continue
                            logger.info(f"⚡ [Barge-in] Interrupt while Rio speaking (RMS:{rms:.0f})")
                            if not self.interrupt_pending:
                                self.interrupt_pending = True
                                self.pending_interrupt_reason = "customer_speaking"
                                self._pause_playback_for_interrupt()
                                self._cancel_pending_llm_dispatch()
                            if (now - self._last_clear_ts) * 1000 >= self.barge_clear_cooldown_ms:
                                await self.communicator.clear_audio_buffer()
                                self._last_clear_ts = now
                            speech_counter = 0
                            continue

                        # Rio is silent — customer taking their turn. Retrigger cooldown: don't flood LLM with repeated triggers
                        if (now - self._last_barge_trigger_ts) * 1000 < self.barge_retrigger_cooldown_ms:
                            speech_counter = 0
                            continue

                        logger.info(f"⚡ [Customer turn] Speech detected (RMS:{rms:.0f}) — sending to LLM")
                        self._last_barge_trigger_ts = now
                        await self._handle_barge_in(reason="customer_speaking")
                        speech_counter = 0
                else:
                    silence_counter += 1
                    if silence_counter > SILENCE_RESET_FRAMES:
                        speech_counter = 0

        # encoding, rate = "pcm_mulaw", "8000"
        encoding, rate = self.audio_encoding, self.audio_sample_rate
        stt_start_time = time.time()
        last_final_transcript = ""
        current_turn_transcript = ""

        fan_out_task = asyncio.create_task(_fan_out())
        barge_task = asyncio.create_task(_barge_in_detector())

        try:
            async for result in self.stt_service.transcribe(_stt_gen(), encoding, rate):
                transcript = result.get("transcript", "")
                is_final = result.get("is_final", False)
                res_type = result.get("type", "transcript")

                if transcript:
                    logger.debug(f"🎤 {'FINAL' if is_final else 'Interim'}: {transcript}")
                    current_turn_transcript = transcript

                if is_final or res_type == "end_of_turn":
                    if not current_turn_transcript or current_turn_transcript == last_final_transcript:
                        continue

                    # distinguish *real* echo (STT picked up Rio's own voice) from a legitimate user turn that happens during Rio's playback.  The previous blanket "Rio speaking → drop" rule silenced customers whose speech the barge detector failed to catch (e.g. RMS below threshold during back-to-back TTS guard windows).  Now we drop only when the transcript matches one of the last 3 Rio sentences (prefix / exact match).  Fresh content is treated as a confirmed barge-in: pause Rio, raise interrupt_pending so downstream logic processes the turn properly.
                    if not self.interrupt_pending and (self.is_rio_speaking or not self.sentence_queue.empty()):
                        if self._is_echo_transcript(current_turn_transcript):
                            logger.info(f"🔇 Echo ignored: '{current_turn_transcript}'")
                            current_turn_transcript = ""
                            continue
                        # New content from the user mid-playback — promote to confirmed interrupt so the rest of this loop treats it as a real turn.  Pause playback + clear audio so Rio's voice doesn't talk over the customer.
                        logger.info(f"⚡ [Mid-playback turn] '{current_turn_transcript}' (no barge fired) — treating as interrupt")
                        self.interrupt_pending = True
                        self.pending_interrupt_reason = "stt_caught_user_speaking"
                        try:
                            self._pause_playback_for_interrupt()
                        except Exception:  # noqa: BLE001
                            pass
                        try:
                            await self.communicator.clear_audio_buffer()
                        except Exception:  # noqa: BLE001
                            pass

                    last_final_transcript = current_turn_transcript
                    logger.info(f"🎤 [STT] FINAL: {current_turn_transcript}")
                    self.last_customer_speech_time = time.time()
                    self.last_user_transcript = current_turn_transcript
                    self.silence_reengage_count = 0
                    # Track whether the customer named a 1-5 — used by the
                    # forced-feedback-ask gate so we don't pester someone
                    # who already gave a rating.
                    if self._customer_uttered_rating(current_turn_transcript):
                        self.user_gave_rating_this_call = True
                    logger.info(f"⏰ [VoicePipeline] Last customer speech time: {self.last_customer_speech_time}")
                    # Latency for THIS turn — measured from when listening for the next user turn began.  Capture it now, then immediately reset so the interrupt path's `continue` below cannot leak the clock across turns (which made stt_ms grow linearly with call duration).  Sanity-cap at 30s so a stuck pipeline doesn't poison percentile aggregates downstream.
                    latency = min(time.time() - stt_start_time, 30.0)
                    stt_start_time = time.time()

                    # Persist user turn; include any ASR segment data if provider returned it
                    self.transcript_manager.add_user_turn(current_turn_transcript, segments=result.get('segments'))
                    # Mirror into the pipeline's accumulator for backward compatibility
                    self.transcript_accumulator.append(f"User: {current_turn_transcript}")

                    # Publish live sentiment update to any subscribed dashboard clients
                    try:
                        sentiment_data = sentiment_broadcaster.analyze_sentiment(current_turn_transcript)
                        sentiment_data["interaction_id"] = self.interaction_id
                        asyncio.create_task(
                            sentiment_broadcaster.publish(str(self.interaction_id), sentiment_data, self.company_id)
                        )
                    except Exception as _se:
                        logger.debug("Sentiment publish skipped: %s", _se)

                    # Real-time competitor mention detection
                    try:
                        from services.competitor_service import detect_competitors_in_utterance, get_counter_script_injection
                        from database import engine as _db_engine
                        from sqlmodel import Session as _DbSession
                        with _DbSession(_db_engine) as _csess:
                            _new_mentions = detect_competitors_in_utterance(
                                session=_csess,
                                company_id=self.company_id,
                                lead_id=self.lead_id,
                                interaction_id=self.interaction_id,
                                utterance=current_turn_transcript,
                            )
                        for _m in _new_mentions:
                            with _DbSession(_db_engine) as _csess2:
                                _injection = get_counter_script_injection(
                                    _csess2, self.company_id, _m.competitor_name
                                )
                            if _injection:
                                self.llm_service.update_system_prompt(
                                    self.llm_service.system_prompt + _injection
                                )
                                logger.info("[Pipeline] Counter-script injected for: %s", _m.competitor_name)
                    except Exception as _ce:
                        logger.debug("Competitor detection skipped: %s", _ce)

                    # Phase 2: Language detection — runs every turn via fasttext (<5ms)
                    self.language_detector.on_turn()
                    detected_lang = await self.language_detector.check(current_turn_transcript)
                    if detected_lang:
                        lang_code = detected_lang[:2]
                        logger.info("[Pipeline] Language auto-switched to: %s", detected_lang)
                        # Update lead_language so TTS/filler use correct language
                        self.lead_language = f"{lang_code}-IN" if lang_code in {"hi", "ta", "te", "kn", "ml", "mr", "bn", "gu", "pa"} else "en-IN"
                        # Azure TTS: switch neural voice to match detected language
                        if self.tts_provider == "azure" and hasattr(self.tts_service, "voice_name"):
                            _AZURE_VOICE_MAP = {
                                "en": "en-US-JennyNeural",
                                "hi": "hi-IN-SwaraNeural",
                                "ta": "ta-IN-PallaviNeural",
                                "te": "te-IN-ShrutiNeural",
                                "mr": "mr-IN-AarohiNeural",
                                "gu": "gu-IN-DhwaniNeural",
                                "bn": "bn-IN-TanishaaNeural",
                                "kn": "kn-IN-SapnaNeural",
                                "ml": "ml-IN-SobhanaNeural",
                                "pa": "pa-Guru-IN-VaaniNeural",
                                "fr": "fr-FR-DeniseNeural",
                                "es": "es-ES-ElviraNeural",
                                "de": "de-DE-KatjaNeural",
                                "pt": "pt-BR-FranciscaNeural",
                                "id": "id-ID-GadisNeural",
                                "ms": "ms-MY-YasminNeural",
                            }
                            new_voice = _AZURE_VOICE_MAP.get(lang_code)
                            if new_voice:
                                self.tts_service.voice_name = new_voice
                                logger.info("[Pipeline] Azure TTS voice → %s", new_voice)
                        lang_suffix = self.language_detector.switcher.get_language_prompt_suffix()
                        if lang_suffix:
                            try:
                                self.llm_service.add_system_message(lang_suffix)
                            except Exception as exc:
                                logger.warning("[Pipeline] Language prompt suffix failed: %s", exc)

                    # Voicemail detection — check every turn while in detection window
                    if self.voicemail_handler.enabled:
                        self.voicemail_handler.on_user_speech(current_turn_transcript)
                        full_transcript_so_far = " ".join(
                            line.replace("User: ", "").replace("Rio: ", "")
                            for line in self.transcript_accumulator
                        )
                        try:
                            vm_result = await self.voicemail_handler.check(full_transcript_so_far)
                        except Exception as _vme:
                            logger.debug("[Pipeline] Voicemail check error: %s", _vme)
                            vm_result = None
                        if self.voicemail_handler.is_detected:
                            logger.info("[Pipeline] Voicemail detected — hanging up")
                            self._clear_sentence_queue()
                            if self.current_tts_task and not self.current_tts_task.done():
                                self.current_tts_task.cancel()
                            break  # exits STT loop → pipeline shuts down → Twilio hangs up

                    normalized_transcript = current_turn_transcript.strip()
                    if normalized_transcript:
                        if self.pending_user_turn_text:
                            self.pending_user_turn_text = (
                                f"{self.pending_user_turn_text} {normalized_transcript}"
                            ).strip()
                        else:
                            self.pending_user_turn_text = normalized_transcript

                    if self.current_llm_task and not self.current_llm_task.done():
                        self.current_llm_task.cancel()

                    if self.interrupt_pending:
                        if not normalized_transcript or self._is_echo_transcript(normalized_transcript):
                            self._handle_false_positive_interrupt()
                        else:
                            self._handle_confirmed_interrupt(latency)
                        current_turn_transcript = ""
                        continue

                    self._schedule_llm_dispatch(latency)
                    # stt_start_time already reset above (immediately after capturing latency).  No reset needed here.
                    current_turn_transcript = ""

        except Exception as e:
            logger.error(f"❌ [VoicePipeline] STT loop error: {e}")
        finally:
            # Defensive: ensure speaker is not stuck in pause-mode wait when we drop the shutdown sentinel.  resume_event.set() wakes any pending resume waiter so the queue.get() can read the None.
            try:
                self.resume_event.set()
            except Exception:  # noqa: BLE001
                pass

            # Phase 3: Play final call message before hangup (if configured)
            final_msg = self._get_final_call_message()
            if final_msg:
                logger.info("[Pipeline] Queuing final call message: %r", final_msg)
                await self.sentence_queue.put((final_msg, True))
                await asyncio.sleep(0.5)

            await self.sentence_queue.put(None)
            await speaker_task
            fan_out_task.cancel()
            barge_task.cancel()
            ingest_task.cancel()
            silence_task.cancel()
            # Unregister pipeline for event injection
            try:
                from services.voice.event_injection_service import unregister_pipeline
                unregister_pipeline(int(self.interaction_id))
            except (ValueError, TypeError):
                pass
            self.flush_transcript()
            logger.info(f"✅ [VoicePipeline] Call ended. Interaction ID: {self.interaction_id}")
            logger.info(f"📜 [VoicePipeline] Full Transcript: {self.transcript_accumulator}")
            logger.info("📜 Post-call transcript flush complete.")
            self._run_post_call_actions()

    async def _silence_watcher(self):
        """
        Fires ONLY when:
        1. Rio finished speaking (is_rio_speaking = False, queue empty)
        2. Customer has NOT spoken since Rio finished
        3. Silence has lasted > threshold since Rio stopped
        """
        # Per-company override > env > hardcoded default.  Lets the user tune
        # via /settings without restarting the backend.  Defaults: 6s silence +
        # 3s check cadence → fires within 6-9s of last activity.
        def _setting_or_env(key: str, env_default: str) -> float:
            try:
                from credentials_service import get_company_setting_value
                from database import engine as _eng
                from sqlmodel import Session as _Sess
                if self.company_id:
                    with _Sess(_eng) as _s:
                        v = get_company_setting_value(_s, self.company_id, key)
                        if v is not None and str(v).strip():
                            return float(v)
            except Exception:  # noqa: BLE001
                pass
            return float(os.getenv(key, env_default))

        _silence_cfg = self.runtime_json.get("silence", {})
        SILENCE_THRESHOLD = float(_silence_cfg.get("threshold_s") or _setting_or_env("SILENCE_THRESHOLD_S", "6.0"))
        CHECK_INTERVAL = float(_silence_cfg.get("check_interval_s") or _setting_or_env("SILENCE_CHECK_INTERVAL_S", "3.0"))
        MAX_REENGAGES = int(_silence_cfg.get("max_reengages", 1))
        logger.info(
            "[Pipeline] Silence-watcher: threshold=%.1fs check=%.1fs max_reengages=%d",
            SILENCE_THRESHOLD, CHECK_INTERVAL, MAX_REENGAGES,
        )

        while True:
            await asyncio.sleep(CHECK_INTERVAL)

            # Skip if Rio is still talking or has more queued
            if self.is_rio_speaking or not self.sentence_queue.empty():
                continue

            # How long since Rio finished speaking?
            silence_since_rio_finished = time.time() - self.last_rio_speech_end_time
        
            # How long since customer last spoke?
            silence_since_customer_spoke = time.time() - self.last_customer_speech_time

            if (silence_since_rio_finished > SILENCE_THRESHOLD 
                    and self.last_customer_speech_time < self.last_rio_speech_end_time):
                if self.silence_reengage_count >= MAX_REENGAGES:
                    continue

                if self.last_context_type == "pricing":
                    phrase = "I'm still here. Take your time, and I can compare the options if you want."
                elif self.last_context_type == "demo":
                    phrase = "I'm still here. If you want, I can go deeper on any part."
                else:
                    phrase = "I'm still here. Take your time."

                logger.info(f"🔔 [Silence Watcher] {silence_since_rio_finished:.1f}s since Rio finished — re-engaging")
                await self.sentence_queue.put((phrase, True))
                self.silence_reengage_count += 1

                # Reset so it doesn't fire again immediately
                self.last_rio_speech_end_time = time.time()
                self.last_context_type = "general"


    async def _await_tts_with_retry(self, tts_task: asyncio.Task, speak_kwargs: dict) -> None:
        """Await a TTS task. On failure, retry once; only queue fallback phrase if retry
        doesn't succeed within 500ms. The fallback task is cancelled if a new LLM stream
        starts before it fires (see _process_llm_response)."""
        try:
            await tts_task
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[TTS] First attempt failed: %s — retrying", exc)

        retry_success = asyncio.Event()

        async def _retry() -> None:
            try:
                await self.tts_service.speak(**speak_kwargs)
                retry_success.set()
            except Exception as retry_exc:
                logger.error("[TTS] Retry also failed: %s", retry_exc)

        retry_task = asyncio.create_task(_retry())

        async def _debounced_fallback() -> None:
            try:
                await asyncio.sleep(0.5)
                if not retry_success.is_set():
                    logger.warning("[TTS] Retry not successful within 500ms — queueing fallback phrase")
                    await self.sentence_queue.put(("Just a moment.", True))
            except asyncio.CancelledError:
                pass

        self._pending_tts_fallback_task = asyncio.create_task(_debounced_fallback())
        await retry_task
        if self._pending_tts_fallback_task and not self._pending_tts_fallback_task.done():
            self._pending_tts_fallback_task.cancel()
            self._pending_tts_fallback_task = None

    async def _speaker_loop(self):
        """Continuously pulls sentences from the queue and speaks them."""
        async with aiohttp.ClientSession() as session:
            # Persistent WebSockets for specific providers
            dg_ws = None
            el_ws = None
            c_ws = None
            sv_ws = None
            
            try:
                # Setup persistent connections if needed
                if self.tts_provider == "deepgram":
                    dg_api_key = self.integration_keys.get("DEEPGRAM_API_KEY")
                    if not dg_api_key:
                        logger.warning("⚠️ Deepgram API key missing; falling back to REST for TTS.")
                    else:
                        dg_voice = self.tts_service.model
                        dg_url = f"wss://api.deepgram.com/v1/speak?model={dg_voice}&encoding=mulaw&sample_rate=8000"
                        dg_headers = {"Authorization": f"Token {dg_api_key}"}
                        try:
                            dg_ws = await session.ws_connect(dg_url, headers=dg_headers)
                            logger.info(f"🎯 Deepgram TTS Persistent WebSocket Connected (model={dg_voice})")
                        except Exception as exc:
                            dg_ws = None
                            logger.error(f"❌ Deepgram TTS WebSocket connect failed: {exc}")
                
                elif self.tts_provider == "elevenlabs":
                    el_api_key = self.integration_keys.get("ELEVENLABS_API_KEY")
                    if not el_api_key:
                        logger.warning("⚠️ ElevenLabs API key missing; falling back to REST for TTS.")
                    else:
                        el_voice = self.tts_service.voice_id
                        el_model = self.tts_service.model
                        el_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{el_voice}/stream-input?model_id={el_model}&output_format=ulaw_8000"
                        el_headers = {"xi-api-key": el_api_key}
                        try:
                            el_ws = await session.ws_connect(el_url, headers=el_headers)
                            # Send BOS (beginning-of-stream) to initialize the persistent connection
                            await el_ws.send_json({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}})
                            logger.info(f"🎯 ElevenLabs TTS Persistent WebSocket Connected (voice={el_voice}, model={el_model})")
                        except Exception as exc:
                            el_ws = None
                            logger.error(f"❌ ElevenLabs TTS WebSocket connect failed: {exc}")
                elif self.tts_provider == "cartesia":
                    c_api_key = self.integration_keys.get("CARTESIA_API_KEY")
                    if not c_api_key:
                        logger.warning("⚠️ Cartesia API key missing; falling back to REST for TTS.")
                    else:
                        c_url = f"wss://api.cartesia.ai/tts/websocket?api_key={c_api_key}&cartesia_version=2025-04-16"
                        try:
                            c_ws = await session.ws_connect(c_url)
                            logger.info("🎯 Cartesia TTS Persistent WebSocket Connected (aiohttp)")
                        except Exception as exc:
                            c_ws = None
                            logger.error(f"❌ Cartesia TTS WebSocket connect failed: {exc}")

                elif self.tts_provider == "sarvam":
                    sv_api_key = self.integration_keys.get("SARVAM_API_KEY")
                    if not sv_api_key:
                        logger.warning("⚠️ Sarvam API key missing; falling back to REST for TTS.")
                    else:
                        sv_headers = {"api-subscription-key": sv_api_key}
                        from services.ai.tts.sarvam import SarvamTTS
                        try:
                            sv_ws = await session.ws_connect(SarvamTTS.WS_URL, headers=sv_headers)
                            sv_config = SarvamTTS.ws_config_frame_static(
                                model=self.tts_service.model,
                                speaker=self.tts_service.speaker,
                                language=self.lead_language,
                            )
                            await sv_ws.send_str(sv_config)
                            logger.info(f"🎯 Sarvam TTS Persistent WebSocket Connected (language={self.lead_language})")
                        except Exception as exc:
                            sv_ws = None
                            logger.error(f"❌ Sarvam TTS WebSocket connect failed: {exc}")

            # Main Speaker Loop.  Race resume_event against the queue so a shutdown sentinel (None) puts during pause-mode hang-up wakes this loop immediately.  Without the race, hang-up during an active barge-in pause would leave the speaker blocked on resume_event.wait() forever, stalling teardown until the outer timeout fires (and post-call flush with it).
                # WebSocket health monitor — ping every 25s to detect silent TCP drops
                # before the next sentence fails. Sets ws ref to None so reconnect fires.
                _ws_refs = {"c": c_ws, "sv": sv_ws, "el": el_ws, "dg": dg_ws}

                async def _ws_health_loop():
                    await asyncio.sleep(25)
                    while True:
                        for _name, _ws_key in [("cartesia", "c"), ("sarvam", "sv"),
                                                ("elevenlabs", "el"), ("deepgram", "dg")]:
                            _ws = _ws_refs.get(_ws_key)
                            if _ws and not _ws.closed:
                                try:
                                    await asyncio.wait_for(_ws.ping(), timeout=5.0)
                                except Exception:
                                    logger.warning("[WSHealth] %s ping failed — marking for reconnect", _name)
                                    _ws_refs[_ws_key] = None
                        await asyncio.sleep(25)

                _ws_health_task = asyncio.create_task(_ws_health_loop())

                while True:
                    resume_task = asyncio.create_task(self.resume_event.wait())
                    sentence_task = asyncio.create_task(self.sentence_queue.get())
                    done, pending = await asyncio.wait(
                        {resume_task, sentence_task},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    for p in pending:
                        p.cancel()

                    if sentence_task in done:
                        queue_item = sentence_task.result()
                        if queue_item is None:
                            break
                        
                        # Unpack (text, is_final) tuple.
                        # For robustness, handle cases where a single string might still be in the queue.
                        if isinstance(queue_item, tuple):
                            text_to_speak, is_final = queue_item
                        else:
                            text_to_speak, is_final = queue_item, True

                        # Delivery still gated — wait for resume if paused.
                        if not self.resume_event.is_set():
                            await self.resume_event.wait()
                    else:
                        # resume signaled with empty queue — loop back.
                        continue

                    # Track what we actually emit to TTS this turn.
                    if isinstance(text_to_speak, str) and text_to_speak.strip():
                        self.last_rio_spoken.append(text_to_speak.strip())
                        # Enqueue mark tracking record
                        try:
                            _enqueue_mark(self.session, self.company_id, int(self.interaction_id), text_to_speak)
                        except Exception:
                            pass
                    elif isinstance(text_to_speak, tuple):
                        logger.error("🚨 [VoicePipeline] Unexpected tuple in speaker loop: %r", text_to_speak)
                        text_to_speak = str(text_to_speak[0]) if text_to_speak else ""

                    if not self.communicator.stream_sid:
                        logger.warning("⚠️ Speaker loop waiting for stream_sid...")
                        await asyncio.sleep(0.5)

                    if self.tts_provider == "cartesia":
                        if not c_ws or c_ws.closed:
                            c_api_key = self.integration_keys.get("CARTESIA_API_KEY")
                            if not c_api_key:
                                logger.warning("⚠️ Cartesia API key missing; cannot reopen websocket.")
                                c_ws = None
                            else:
                                c_url = f"wss://api.cartesia.ai/tts/websocket?api_key={c_api_key}&cartesia_version=2025-04-16"
                                try:
                                    c_ws = await session.ws_connect(c_url)
                                    logger.info("🎯 Cartesia TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    c_ws = None
                                    logger.error(f"❌ Cartesia TTS WebSocket reconnect failed: {exc}")

                    elif self.tts_provider == "elevenlabs":
                        if not el_ws or el_ws.closed:
                            el_api_key = self.integration_keys.get("ELEVENLABS_API_KEY")
                            if not el_api_key:
                                logger.warning("⚠️ ElevenLabs API key missing; cannot reopen websocket.")
                                el_ws = None
                            else:
                                el_voice = self.tts_service.voice_id
                                el_model = self.tts_service.model
                                el_url = f"wss://api.elevenlabs.io/v1/text-to-speech/{el_voice}/stream-input?model_id={el_model}&output_format=ulaw_8000"
                                el_headers = {"xi-api-key": el_api_key}
                                try:
                                    el_ws = await session.ws_connect(el_url, headers=el_headers)
                                    await el_ws.send_json({"text": " ", "voice_settings": {"stability": 0.5, "similarity_boost": 0.8}})
                                    logger.info("🎯 ElevenLabs TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    el_ws = None
                                    logger.error(f"❌ ElevenLabs TTS WebSocket reconnect failed: {exc}")

                    elif self.tts_provider == "deepgram":
                        if not dg_ws or dg_ws.closed:
                            dg_api_key = self.integration_keys.get("DEEPGRAM_API_KEY")
                            if not dg_api_key:
                                logger.warning("⚠️ Deepgram API key missing; cannot reopen websocket.")
                                dg_ws = None
                            else:
                                dg_voice = self.tts_service.model
                                dg_url = f"wss://api.deepgram.com/v1/speak?model={dg_voice}&encoding=mulaw&sample_rate=8000"
                                dg_headers = {"Authorization": f"Token {dg_api_key}"}
                                try:
                                    dg_ws = await session.ws_connect(dg_url, headers=dg_headers)
                                    logger.info("🎯 Deepgram TTS Persistent WebSocket (Re)Connected")
                                except Exception as exc:
                                    dg_ws = None
                                    logger.error(f"❌ Deepgram TTS WebSocket reconnect failed: {exc}")

                    elif self.tts_provider == "sarvam":
                        if not sv_ws or sv_ws.closed:
                            sv_api_key = self.integration_keys.get("SARVAM_API_KEY")
                            if not sv_api_key:
                                logger.warning("⚠️ Sarvam API key missing; cannot reopen websocket.")
                                sv_ws = None
                            else:
                                sv_headers = {"api-subscription-key": sv_api_key}
                                from services.ai.tts.sarvam import SarvamTTS
                                try:
                                    sv_ws = await session.ws_connect(SarvamTTS.WS_URL, headers=sv_headers)
                                    sv_config = SarvamTTS.ws_config_frame_static(
                                        model=self.tts_service.model,
                                        speaker=self.tts_service.speaker,
                                        language=self.lead_language,
                                    )
                                    await sv_ws.send_str(sv_config)
                                    logger.info(f"🎯 Sarvam TTS Persistent WebSocket (Re)Connected (language={self.lead_language})")
                                except Exception as exc:
                                    sv_ws = None
                                    logger.error(f"❌ Sarvam TTS WebSocket reconnect failed: {exc}")
                
                    tts_text = clean_voice_text(text_to_speak) if text_to_speak else ""
                    logger.info(f"🗣️ [Speaker Loop] Starting TTS for: '{tts_text}' (final={is_final})")
                    normalized_sentence = self._normalize_text(tts_text)
                    if normalized_sentence:
                        self.last_rio_sentences.append(normalized_sentence)
                    # Generate a unique context_id per sentence for better multiplexing
                    turn_context_id = f"ctx_{self.interaction_id}_{int(time.time()*1000)}"

                    self.is_rio_speaking = True
                    self.last_tts_start_time = time.time()

                    # For Cartesia: fire TTS request AND immediately check for next sentence
                    # Cartesia queues them server-side via context_id
                    if self.tts_provider == "cartesia" and c_ws:
                        _speak_kw = dict(
                            text=tts_text,
                            communicator=self.communicator,
                            ws_to_use=c_ws,
                            context_id=turn_context_id,
                            is_final=is_final,
                            aiohttp_session=session,
                        )
                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(**_speak_kw)
                        )
                        _tts_cancelled = False
                        try:
                            await self._await_tts_with_retry(self.current_tts_task, _speak_kw)
                        except asyncio.CancelledError:
                            _tts_cancelled = True
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            if not _tts_cancelled:
                                self._record_tts_usage(tts_text)
                            self.is_rio_speaking = False
                            self.last_rio_speech_end_time = time.time()
                            self.sentence_queue.task_done()
                    else:
                        # Determine which persistent WS to pass as generic 'ws_to_use'
                        active_ws = None
                        if self.tts_provider == "deepgram":
                            active_ws = dg_ws
                        elif self.tts_provider == "elevenlabs":
                            active_ws = el_ws
                        elif self.tts_provider == "sarvam":
                            active_ws = sv_ws
                        # mimo is REST-based — no persistent WebSocket, active_ws stays None

                        _speak_kw = dict(
                            text=tts_text,
                            communicator=self.communicator,
                            ws_to_use=active_ws,
                            context_id=turn_context_id,
                            is_final=is_final,
                            aiohttp_session=session,
                        )
                        self.current_tts_task = asyncio.create_task(
                            self.tts_service.speak(**_speak_kw)
                        )
                        _tts_cancelled = False
                        try:
                            await self._await_tts_with_retry(self.current_tts_task, _speak_kw)
                        except asyncio.CancelledError:
                            _tts_cancelled = True
                            logger.info("TTS Task Cancelled (Barge-in / Interrupted).")
                        finally:
                            if not _tts_cancelled:
                                self._record_tts_usage(tts_text)
                            self.is_rio_speaking = False
                            self.last_rio_speech_end_time = time.time()
                            self.sentence_queue.task_done()

            finally:
                # Cleanup WS health monitor
                _ws_health_task.cancel()
                # Cleanup persistent WebSockets
                if dg_ws: await dg_ws.close()
                if el_ws: await el_ws.close()
                if c_ws: await c_ws.close()
                if sv_ws: await sv_ws.close()

    async def _handle_barge_in(self, reason: str = "Unknown"):
        """Interrupts current AI activities."""
        logger.info(f"🛑 Barge-in! Interrupting AI. Reason: '{reason}'")
        if not self.interrupt_pending:
            self.interrupt_pending = True
            self.pending_interrupt_reason = reason
            self._pause_playback_for_interrupt()
            self._cancel_pending_llm_dispatch()
        await self.communicator.clear_audio_buffer()
        self.llm_service.clean_interrupted_tool_calls()
        self.current_turn_user_text = ""
        self.is_rio_speaking = False

    def _annotate_trace(self, span_status: str = "ok") -> None:
        """
        Attach trace_id/span_id/turn_index/span_status to the LatencyLog row
        just written by save_latency(). Called immediately after save_latency().
        Never raises — trace annotation is best-effort.
        """
        try:
            interaction_id_int = int(self.interaction_id)
        except (ValueError, TypeError):
            return  # Anonymous/session calls — nothing to annotate

        try:
            from sqlalchemy import text as _text
            from database import engine as _db_engine
            from sqlmodel import Session as _TraceSession

            span_id = _uuid.uuid4().hex[:16]
            with _TraceSession(_db_engine) as s:
                s.execute(
                    _text("""
                        UPDATE latencylog
                        SET trace_id    = :trace_id,
                            span_id     = :span_id,
                            turn_index  = :turn_index,
                            span_status = :span_status
                        WHERE id = (
                            SELECT id FROM latencylog
                            WHERE interaction_id = :iid
                            ORDER BY id DESC
                            LIMIT 1
                        )
                    """),
                    {
                        "trace_id": self.trace_id,
                        "span_id": span_id,
                        "turn_index": self.turn_index,
                        "span_status": span_status,
                        "iid": interaction_id_int,
                    },
                )
                s.commit()
            self.turn_index += 1
        except Exception as exc:
            logger.debug("Trace annotation skipped: %s", exc)

    def _record_tts_usage(self, text: str) -> None:
        try:
            if not text:
                return
            try:
                iid = int(self.interaction_id)
            except (ValueError, TypeError):
                iid = None
            from services.observability.usage_tracker import record_usage
            record_usage(
                self.session,
                service_type="tts",
                provider=getattr(self.tts_service, "provider", "unknown"),
                model=getattr(self.tts_service, "model", None),
                characters=len(text),
                company_id=self.company_id,
                user_id=self.user_id,
                interaction_id=iid,
                context="voice_turn",
            )
        except Exception as exc:
            logger.debug("_record_tts_usage skipped: %s", exc)

    def _record_llm_usage(self, usage: dict) -> None:
        try:
            if not usage or not any(usage.values()):
                return
            try:
                iid = int(self.interaction_id)
            except (ValueError, TypeError):
                iid = None
            from services.observability.usage_tracker import record_usage
            record_usage(
                self.session,
                service_type="llm",
                provider=getattr(self.llm_service, "provider", "unknown"),
                model=getattr(self.llm_service, "model", None),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                company_id=self.company_id,
                user_id=self.user_id,
                interaction_id=iid,
                context="voice_turn",
            )
        except Exception as exc:
            logger.debug("_record_llm_usage skipped: %s", exc)

    def save_latency(self, engine_name, stt, llm, tts, stt_p=None, stt_m=None, llm_p=None, llm_m=None, tts_p=None, tts_m=None):
        """Saves turn-level latency metrics to DB."""
        try:
            # Handle non-integer interaction_id (e.g., session strings)
            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None
                logger.debug(f"ℹ️ Interaction ID '{self.interaction_id}' is a session string. Saving latency as anonymous.")

            log_user_id = self.user_id
            log_lead_id = self.lead_id

            log = LatencyLog(
                company_id=self.company_id,
                interaction_id=interaction_id_int,
                user_id=log_user_id,
                lead_id=log_lead_id,
                engine=engine_name,
                stt_ms=round(stt * 1000, 2),
                llm_ms=round(llm * 1000, 2),
                tts_ms=round(tts * 1000, 2),
                total_ms=round((stt + llm + tts) * 1000, 2),
                stt_provider=stt_p,
                stt_model=stt_m,
                llm_provider=llm_p,
                llm_model=llm_m,
                tts_provider=tts_p,
                tts_model=tts_m,
                notes=f"ID: {self.interaction_id}" if interaction_id_int is None else None,
            )
            self.session.add(log)
            self.session.commit()

            # Detailed Logging (unchanged)
            logger.info(
                f"⏱️ [Latency Saved] {engine_name} | Total: {log.total_ms}ms\n"
                f"   🎙️ STT: {stt*1000:.0f}ms ({stt_p}/{stt_m})\n"
                f"   🧠 LLM: {llm*1000:.0f}ms ({llm_p}/{llm_m})\n"
                f"   🔊 TTS: {tts*1000:.0f}ms ({tts_p}/{tts_m})"
            )
        except Exception as e:
            logger.error(f"❌ Error saving latency: {e}")

    def save_transcript(self, engine_name="voice_call"):
        """During call: just mark dirty. DB write is deferred to flush_transcript()."""
        self._transcript_dirty = True

    def _build_transcript_content(self) -> str:
        return "\n".join(line for line in self.transcript_accumulator if line and line.strip())

    def flush_transcript(self, engine_name="voice_call"):
        """Called ONCE after call ends. Writes full transcript to DB using a fresh session
        to avoid stale/rolled-back session state from the long-running call."""
        if not self._transcript_dirty:
            return
        try:
            full_transcript = self._build_transcript_content()
            if not full_transcript.strip():
                return

            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None

            from database import engine as _db_engine
            from sqlmodel import Session as _Session
            with _Session(_db_engine) as fresh_session:
                db_i = None
                if interaction_id_int:
                    db_i = fresh_session.get(Interaction, interaction_id_int)

                if not db_i:
                    if not self.user_id:
                        logger.warning("No user context for transcript flush fallback; skipping.")
                        return
                    db_i = Interaction(
                        company_id=self.company_id,
                        lead_id=self.lead_id,
                        user_id=self.user_id,
                        type="call",
                        channel="call",
                        direction="outbound",
                        source="voice_pipeline",
                        content=f"Voice Interaction ({engine_name})",
                        transcript=full_transcript,
                        status="completed",
                        started_at=utc_now(),
                        ended_at=utc_now(),
                        created_by=self.user_id,
                        updated_by=self.user_id,
                    )
                    fresh_session.add(db_i)
                    fresh_session.commit()
                    fresh_session.refresh(db_i)
                    if not interaction_id_int:
                        self.interaction_id = str(db_i.id)
                else:
                    db_i.transcript = full_transcript
                    db_i.status = "completed"
                    db_i.ended_at = utc_now()
                    db_i.updated_at = utc_now()
                    db_i.updated_by = self.user_id
                    fresh_session.add(db_i)
                    fresh_session.commit()

            # After the main DB write, persist any ASR segment metadata captured by the TranscriptManager.
            try:
                # This delegates a second, idempotent update to the transcript manager which
                # stores normalized ASR segments into interaction.metadata_json.
                self.transcript_manager.save_transcript(engine_name)
            except Exception as _e:
                logger.debug("TranscriptManager.save_transcript failed during flush: %s", _e)

            self._transcript_dirty = False
            logger.info(f"📜 [Transcript Flushed] ID: {interaction_id_int or 'new'} | {len(full_transcript)} chars | {len(self.transcript_accumulator)} lines")
        except Exception as e:
            logger.error(f"❌ Error flushing transcript: {e}")

    def _run_post_call_actions(self) -> None:
        """
        Triggered once after the call ends and transcript is flushed.
        Saves a structured call summary and updates lead outreach metadata.
        Runs synchronously in the pipeline teardown (non-blocking errors).
        """
        try:
            from agents.post_call_nurture import CallSummarizer, CRMUpdater
            from models.models import Lead

            # Resolve interaction_id and lead from DB.
            try:
                interaction_id_int = int(self.interaction_id)
            except (ValueError, TypeError):
                interaction_id_int = None

            lead_id: int | None = None
            lead_score_normalized: float = 0.0

            interaction_record: Interaction | None = None
            if interaction_id_int:
                db_i = self.session.get(Interaction, interaction_id_int)
                if db_i:
                    interaction_record = db_i
                    lead_id = db_i.lead_id

            if lead_id:
                lead = self.session.get(Lead, lead_id)
                if lead and lead.lead_score is not None:
                    lead_score_normalized = float(lead.lead_score) / 100.0

            full_transcript = self._build_transcript_content()

            # save structured summary interaction.
            summary = CallSummarizer.summarize_call(
                lead_id=lead_id or 0,
                transcript=full_transcript,
                icp_score=lead_score_normalized,
                sentiment="neutral",
                pain_points=[],
                questions_asked=[],
                bant_answers={},
            )
            if lead_id:
                CallSummarizer.save_summary_to_crm(lead_id, summary, company_id=self.company_id or 0, actor_user_id=self.user_id, parent_interaction_id=interaction_id_int)

            # log the completed call as a CRM interaction note.
            if lead_id:
                line_count = len(self.transcript_accumulator)
                CRMUpdater.log_interaction(
                    lead_id,
                    "call_completed",
                    f"Voice call ended. {line_count} transcript lines recorded. "
                    f"Interaction ID: {self.interaction_id}.",
                    company_id=self.company_id or 0,
                    actor_user_id=self.user_id,
                )

                logger.info(
                    "[PostCall] Nurture actions complete. lead_id=%s interaction=%s",
                    lead_id, self.interaction_id,
                )
                # Save cost record for this call
                try:
                    db_int = self.session.get(Interaction, interaction_id_int) if interaction_id_int else None
                    duration = 0
                    if db_int and db_int.recording_duration:
                        duration = db_int.recording_duration
                    elif db_int and db_int.ended_at and db_int.started_at:
                        duration = int((db_int.ended_at - db_int.started_at).total_seconds())
                    if duration > 0:
                        cost_result = _calc_cost(
                            duration_seconds=duration,
                            stt_provider=self.stt_provider,
                            llm_provider=self.llm_provider,
                            tts_provider=self.tts_provider,
                            session=self.session,
                            company_id=self.company_id,
                        )
                        _save_cost(
                            self.session, self.company_id or 0,
                            interaction_id=interaction_id_int,
                            lead_id=self.lead_id,
                            duration_seconds=duration,
                            **cost_result,
                            stt_provider=self.stt_provider,
                            llm_provider=self.llm_provider,
                            tts_provider=self.tts_provider,
                        )
                except Exception as _ce:
                    logger.debug("[PostCall] Cost save skipped: %s", _ce)

                # Fire webhook for call-ended event (non-blocking)
                try:
                    from services.webhooks.publisher import publish as wh_publish
                    import asyncio as _asyncio
                    _asyncio.create_task(wh_publish(
                        self.company_id, "call.ended", {
                            "interaction_id": self.interaction_id,
                            "lead_id": self.lead_id,
                            "agent_id": getattr(self, 'active_prompt', None) and getattr(self.active_prompt, 'agent_id', None),
                        }
                    ))
                except Exception:
                    pass   # fan-out must never break the call path

                # Vobiz sends recording URL via status-callback (no polling API available).
        except Exception as exc:
            logger.warning("[PostCall] Post-call actions failed (non-fatal): %s", exc)

    async def _handle_dtmf(self, digit: str) -> None:
        """Execute the DTMF menu action mapped to digit."""
        option = self.dtmf_menu.get(digit)
        if not option:
            logger.debug("[DTMF] No menu entry for digit %r — ignored", digit)
            return
        action = option.get("action", "agent")
        label = option.get("label", "")
        value = option.get("value", "")
        logger.info("[DTMF] digit=%r action=%r label=%r value=%r", digit, action, label, value)

        if action == "hangup":
            if label:
                await self.sentence_queue.put((label, True))
                await asyncio.sleep(1.5)
            await self.sentence_queue.put(None)  # shutdown sentinel
        elif action == "transfer":
            if label:
                await self.sentence_queue.put((label, True))
                await asyncio.sleep(1.5)
            if value and self.interaction_id:
                try:
                    from services.call.warm_transfer_service import execute_warm_transfer
                    await asyncio.to_thread(
                        execute_warm_transfer,
                        self.session,
                        self.company_id,
                        self.user_id,
                        int(self.interaction_id),
                        value,
                    )
                    logger.info("[DTMF] Warm transfer initiated to %r", value)
                except Exception as _te:
                    logger.error("[DTMF] Transfer failed: %s", _te)
            await self.sentence_queue.put(None)
        elif action == "repeat_menu":
            prompt = value or label
            if prompt:
                await self.sentence_queue.put((prompt, True))
        # action == "agent" → do nothing, AI continues

    def _get_final_call_message(self) -> str | None:
        """Get the final call message in the current detected language.

        Falls back through: detected language → en → first available → None.
        """
        if not self.final_call_message_lang_map:
            return None

        detected = getattr(self, "language_detector", None)
        current_lang = detected.current_language if detected and detected.enabled else "en"

        msg = self.final_call_message_lang_map.get(current_lang) or self.final_call_message_lang_map.get("en")
        if not msg and self.final_call_message_lang_map:
            msg = next(iter(self.final_call_message_lang_map.values()))

        return msg

    def _strip_markdown(self, text: str) -> str:
        """Removes markdown formatting like **bold**, *italics*, and bullet points for TTS."""
        if not text:
            return ""
        # Remove bold/italics markers
        text = re.sub(r'[*_]{1,3}', '', text)
        # Remove bullet points/list markers at start of lines
        text = re.sub(r'^[\s]*[-+*][\s]+', '', text, flags=re.MULTILINE)
        # Remove hashtags for headers
        text = re.sub(r'#+\s+', '', text)
        return text.strip()

    async def _process_llm_response(self, user_input, stt_latency):
        """Handles LLM generation, tool execution, and recursive follow-ups."""
        llm_start_time = time.time()

        # Only add user message if this is a fresh turn, not a tool recursion
        if user_input:
            self.current_turn_user_text = user_input
            self.llm_service.add_user_message(user_input)
            # Fresh turn — clear the spoken-so-far buffer.  Tool-call recursion leaves it in place so an interruption mid-tool-output still sees what the agent was saying.
            self.last_rio_spoken.clear()
            self._sentences_emitted_this_turn = 0
            # Cancel any pending TTS fallback from the previous turn — it's now stale.
            if self._pending_tts_fallback_task and not self._pending_tts_fallback_task.done():
                self._pending_tts_fallback_task.cancel()
                self._pending_tts_fallback_task = None
        
        # Only expose tools the company actually has connected/enabled — this is
        # what lets the agent use Apollo/Zoho/Cal.com/Calendly/inventory mid-call.
        # When the call is tied to a specific voice agent with an allowlist
        # (VoiceAgentTool rows), further restrict to that agent's tools.
        mistral_tools = get_mistral_tools(self.company_id, agent_id=self.agent_id)
        
        full_reply = ""
        tool_calls = None
        
        async for chunk in self.llm_service.stream(tools=mistral_tools):
            if chunk["type"] == "sentence":
                sentence = chunk["content"]

                stripped = self._strip_json_fragments(sentence)

                # if stripping removed a meaningful chunk, log it
                if stripped != sentence:
                    logger.warning(
                        "🚫 [VoicePipeline] JSON fragments stripped from sentence: %r → %r",
                        sentence[:60], stripped[:60],
                    )

                # if what remains is still technical leakage, discard entirely
                if not stripped or self._is_technical_leakage(stripped):
                    logger.warning("🚫 [VoicePipeline] Discarding JSON-leaked sentence: %r", sentence[:60])
                    continue

                # strip markdown and internal ID patterns
                clean_sentence = self._strip_markdown(stripped)
                clean_sentence = self._filter_technical_speech(clean_sentence)

                if not clean_sentence or len(clean_sentence.strip()) < 2:
                    continue

                if self.filler_service.use_fillers:
                    clean_sentence = self.filler_service.strip_fillers(clean_sentence)
                    if not clean_sentence or len(clean_sentence.strip()) < 2:
                        continue

                if self._is_low_value_fragment(clean_sentence):
                    logger.info("[VoicePipeline] Dropping low-value fragment: %r", clean_sentence)
                    continue

                if (
                    self._sentence_says_goodbye(clean_sentence)
                    and not self.feedback_asked_this_call
                    and not self.user_gave_rating_this_call
                    and not self._should_defer_feedback()
                ):
                    logger.info(
                        "[Pipeline] LLM was about to say goodbye without asking for "
                        "feedback — forcing the 1-5 rating question."
                    )
                    self.feedback_asked_this_call = True
                    self.last_rio_sentences.append(self._feedback_phrase)
                    self.last_rio_spoken.append(self._feedback_phrase)
                    await self.sentence_queue.put((self._feedback_phrase, True))

                
                if self._sentence_asks_feedback(clean_sentence):
                    self.feedback_asked_this_call = True

                # Determine if this phrase is terminal (ends turn) or a prefix chunk.
                # Splitting on , ; counts as a prefix (is_final=False) to enable seamless TTS streaming.
                phrase_is_terminal = bool(re.search(r'[.?!]$', clean_sentence))

                logger.info("📤 [%s -> Queue] Phrase: %r (terminal=%s)", self.llm_provider, clean_sentence, phrase_is_terminal)
                self._sentences_emitted_this_turn += 1
                await self.sentence_queue.put((clean_sentence, phrase_is_terminal))
            elif chunk["type"] == "error":
                self.llm_error_count += 1
                if self.llm_error_count >= 3:
                    fallback_sentence = "I'm sorry, I'm experiencing persistent technical difficulties. Please try calling back in a few minutes."
                    logger.warning(f"🚨 [Smart Fallback] 3 consecutive failures. Queuing final error message.")
                    self._annotate_trace("error")
                else:
                    fallback_sentence = "I'm sorry, I'm having a bit of trouble with my connection. Could you repeat that?"
                    logger.info(f"🔄 [Smart Fallback] Failure #{self.llm_error_count}. Queuing retry message.")
                    self._annotate_trace("error")
                await self.sentence_queue.put((fallback_sentence, True))
                return
            elif chunk["type"] == "finished":
                self.llm_error_count = 0
                full_reply = chunk["full_reply"]
                tool_calls = chunk["tool_calls"]
                self._record_llm_usage(chunk.get("usage") or {})

                reasoning_details = chunk.get("reasoning_details")
                llm_end_time = time.time()
                llm_latency = llm_end_time - llm_start_time
                
                self.llm_service.add_assistant_message(
                    full_reply, 
                    tool_calls=tool_calls, 
                    reasoning_details=reasoning_details
                )
                
                if full_reply:
                    # Strip JSON fragments before recording transcript (keep LLM history untouched)
                    transcript_reply = self._strip_json_fragments(full_reply)
                    self.transcript_manager.add_rio_turn(transcript_reply)
                    # Mirror into the pipeline's accumulator for backward compatibility
                    self.transcript_accumulator.append(f"Rio: {transcript_reply}")
                    self.save_transcript()
                    # Fire webhook for tool-executed event (when we have a full reply)
                    try:
                        from services.webhooks.publisher import publish as wh_publish
                        await wh_publish(self.company_id, "tool.executed", {
                            "interaction_id": self.interaction_id,
                            "lead_id": self.lead_id,
                            "agent_id": getattr(self, 'active_prompt', None) and getattr(self.active_prompt, 'agent_id', None),
                            "tool_calls": [tc.function.name for tc in tool_calls] if tool_calls else [],
                            "response": transcript_reply,
                        })
                    except Exception:
                        pass   # fan-out must never break the call path

                # Always save latency, even for tool-only turns
                self.save_latency(
                    f"{self.stt_provider}-{self.llm_provider}-{self.tts_provider}",
                    stt_latency,
                    llm_latency,
                    self.tts_service.last_latency,
                    stt_p=self.stt_service.provider,
                    stt_m=self.stt_service.model,
                    llm_p=self.llm_service.provider,
                    llm_m=self.llm_service.model,
                    tts_p=self.tts_service.provider,
                    tts_m=self.tts_service.model
                )
                self._annotate_trace("ok")

                if tool_calls:
                    for tc in tool_calls:
                        tool_name = tc.function.name
                        raw_args = tc.function.arguments or "{}"
                        try:
                            tool_args = json.loads(raw_args)
                        except json.JSONDecodeError:
                            # Streaming may concatenate duplicate chunks → "Extra data".
                            # Try extracting the first valid JSON object from the string.
                            m = re.search(r'\{.*?\}', raw_args, re.DOTALL)
                            try:
                                tool_args = json.loads(m.group(0)) if m else {}
                            except Exception:
                                tool_args = {}
                            logger.warning(
                                "⚠️ [VoicePipeline] Malformed tool-call arguments for %s — "
                                "raw: %r  parsed as: %r",
                                tool_name, raw_args[:120], tool_args,
                            )
                        self.transcript_manager.add_system_turn(f"Executing {tool_name}...")
                        # Mirror into the pipeline's accumulator for backward compatibility
                        self.transcript_accumulator.append(f"[System]: Executing {tool_name}...")

                        # Thinking message — keep customer engaged during tool wait
                        thinking_phrases = {
                            "get_product_info":        "Let me pull up the details on that for you.",
                            "book_meeting":            "Let me get that booked for you right now.",
                            "book_demo":               "I'm scheduling that demo for you now.",
                            "send_communication":      "Sending that over to you now.",
                            "get_or_create_lead":      "One moment while I update your record.",
                            "check_icp_qualification": "Let me check if this fits your profile.",
                            "check_guardrails":        "Let me check what I can do on pricing.",
                            "warm_transfer":           "Let me get a human agent on the line for you right now.",
                            "schedule_meeting":         "Great — let me get that meeting scheduled for you right now.",
                            "get_availability":         "Let me check what times are available for you.",
                            "list_bookings":            "One moment, let me pull up your bookings.",
                            "reschedule_meeting":       "Let me move that booking for you now.",
                            "cancel_meeting":           "Let me cancel that booking for you now.",
                            "inventory_lookup":         "Let me check our current stock on that for you.",
                            "inventory_reserve":        "Let me set that aside for you right now.",
                            "search_prospects":         "Let me search for the right prospects for you.",
                            "enrich_prospect":          "Let me pull up more details on that contact for you.",
                            "create_crm_contact":       "Let me save that to your CRM for you now.",
                            "update_crm_contact":       "Let me update that record in your CRM now.",
                            "crm_query":                "Let me look that up in your CRM for you.",
                        }
                        
                        # Update context for silence re-engagement
                        if tool_name in ["get_product_info", "check_guardrails"]:
                            self.last_context_type = "pricing"
                        elif tool_name in ["book_meeting", "book_demo"]:
                            self.last_context_type = "demo"
                        
                        thinking_msg = thinking_phrases.get(tool_name, "One moment, let me look into that for you.")
                        
                        # Only say it if Rio isn't already mid-sentence
                        if self.sentence_queue.empty() and not self.is_rio_speaking:
                            await self.sentence_queue.put((thinking_msg, True))
                            # Small wait so the phrase starts playing before tool execution
                            await asyncio.sleep(0.3)
                        
                        try:
                            result = await execute_mcp_tool(
                                tool_name,
                                tool_args,
                                interaction_id=self.interaction_id,
                                user_id=self.user_id,
                                user=self.user,
                                session=self.session,
                            )
                            
                            # Auto-link interaction to lead if get_or_create_lead result has lead_id
                            if tool_name == "get_or_create_lead" and "lead_id" in result:
                                try:
                                    lid = int(result["lead_id"])
                                    logger.info(f"🔗 Linking interaction {self.interaction_id} to lead {lid}")
                                    try:
                                        interaction_id_int = int(self.interaction_id)
                                        db_i = self.session.get(Interaction, interaction_id_int)
                                        if db_i:
                                            db_i.lead_id = lid
                                            self.session.add(db_i)
                                            self.session.commit()
                                    except (ValueError, TypeError):
                                        pass
                                except Exception as e:
                                    logger.error(f"❌ Failed to link interaction: {e}")

                        except asyncio.CancelledError:
                            logger.info(f"🛑 [VoicePipeline] Tool execution for '{tool_name}' interrupted by barge-in")
                            raise # Re-raise to ensure the whole turn is aborted
                        except Exception as e:
                            logger.error(f"❌ Tool Execution Error: {e}")
                            result = {"error": str(e)}

                        followup_phrase = self._tool_followup_phrase(tool_name, result)
                        if followup_phrase:
                            await self.sentence_queue.put((followup_phrase, True))
                            self.transcript_manager.add_rio_turn(followup_phrase)
                            # Mirror into the pipeline's accumulator for backward compatibility
                            self.transcript_accumulator.append(f"Rio: {followup_phrase}")
                            self.save_transcript()
                            self._sentences_emitted_this_turn += 1
                            try:
                                self.llm_service.add_system_message(self._tool_followup_note(followup_phrase))
                            except Exception as exc:  # noqa: BLE001
                                logger.warning("[VoicePipeline] add_system_message for tool follow-up failed: %s", exc)
                        
                        self.llm_service.add_tool_message(tc.id, tool_name, to_compact(result))
                    
                    logger.info("🔄 Tool results ready. Recursing for final LLM response.")
                    # Recurse with user_input=None to follow the correct tool result -> model response sequence
                    await self._process_llm_response(None, 0)
                self.current_turn_user_text = ""

    def _strip_json_fragments(self, text: str) -> str:
        """
        Strips JSON objects, arrays, and bare key:value pairs from speech text.
        Prose surrounding the JSON is preserved so a sentence like
        "Great, I've noted that! {"email": "x@y.com"}" becomes "Great, I've noted that!"
        """
        if not text:
            return text
        for _ in range(3):
            text = re.sub(r'\{[^{}]*\}', '', text)
        text = re.sub(r'\[[^\[\]]*\]', '', text)
        text = re.sub(
            r'"[a-z_]{2,24}"\s*:\s*(?:"[^"]*"|\d+(?:\.\d+)?|true|false|null)',
            '', text,
        )
        # Clean up leftover commas, spaces, and sentence-ending artifacts
        text = re.sub(r',\s*,', ',', text)
        text = re.sub(r'^\s*[,;]\s*', '', text)
        text = re.sub(r'\s*[,;]\s*$', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _is_technical_leakage(self, text: str) -> bool:
        """Detects if a string looks like raw JSON, tool call fragments, or technical metadata."""
        if not text:
            return False

        trimmed = text.strip()
        # Starts with JSON braces/brackets
        if trimmed.startswith(("{", "[", '{"', '["')):
            return True

        # Contains key-value pair pattern (e.g. "key": "value" or "key": 123)
        if re.search(r'"[a-z_]{2,24}"\s*:\s*(?:"[^"]*"|\d+|true|false|null)', trimmed):
            return True

        # Multiple bare quoted-key:value pairs (comma-separated JSON)
        if len(re.findall(r'"[a-z_]+"\s*:', trimmed)) >= 2:
            return True

        # Contains tool call artifacts
        technical_terms = ['"arguments":', '"name":', '"id":', 'function_call', 'tool_calls', 'call_id']
        if any(term in trimmed for term in technical_terms):
            return True

        # Excessive technical characters ratio
        technical_chars = trimmed.count("{") + trimmed.count("}") + trimmed.count("[") + trimmed.count("]")
        if technical_chars >= 2:
            return True

        return False

    def _filter_technical_speech(self, text: str) -> str:
        """Regex-based safety layer to strip technical leakages from the voice stream."""
        patterns = [
            r"(?i)lead\s+id\s+(?:of\s+)?\d+",
            r"(?i)internal\s+id\s+(?:of\s+)?\d+",
            r"(?i)id\s+is\s+\d+",
            r"(?i)id\s+\d+",
            r"(?i)internal\s+id",
            r"(?i)system\s+record",
            r"(?i)database\s+id",
            r"__META_ID__",
        ]
        for pattern in patterns:
            text = re.sub(pattern, "", text)

        # Clean up awkward double spaces or trailing conjunctions left by stripping
        text = re.sub(r"\s+", " ", text).strip()
        # Remove trailing "with a" or "and" if they were part of an ID phrase
        text = re.sub(r"\b(with a|and|for)\s*$", "", text, flags=re.IGNORECASE).strip()
        return text
    
    def get_full_transcript_self(self) -> str:
        return "\n".join(self.transcript_accumulator)

    async def _audio_generator(self, receiver):
        chunk_count = 0
        async for data in receiver:
            event = data.get("event")
            if event == "media":
                chunk_count += 1
                if chunk_count == 1:
                    logger.info("🎤 First audio chunk received from Twilio")
                yield base64.b64decode(data["media"]["payload"])
            elif event == "stop":
                logger.info("🛑 [Twilio] Stream stopped.")
                break
        logger.info(f"🎤 Audio generator finished. Total chunks: {chunk_count}")

    #async def _audio_generator(self, receiver):
    #    chunk_count = 0
    #    async for data in receiver:
    #        event = data.get("event")
    #        if event == "media":
    #            mulaw_data = base64.b64decode(data["media"]["payload"])
    #            # Convert mulaw to PCM s16le
    #            pcm_data = audioop.ulaw2lin(mulaw_data, 2)
    #            # Upsample from 8000 to 24000 Hz
    #            pcm_data, _ = audioop.ratecv(pcm_data, 2, 1, 8000, 24000, None)
    #            yield pcm_data
    #        elif event == "stop":
    #            break
