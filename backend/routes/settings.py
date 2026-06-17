from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import CompanySetting, CompanySettingsBulkUpsert, User, utc_now, CompanySettingAudit, CompanyPrompt
from utils.encryption import decrypt_value, encrypt_value
from utils import settings_cache as _sc

router = APIRouter(prefix="/crm", tags=["CRM"])

ALL_INTEGRATION_KEYS = {
    # Twilio + Messaging
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "TWILIO_PHONE_NUMBER",
    "PHONE_NUMBER_FROM",
    "WHATSAPP_NUMBER",
    "WHATSAPP_NUMBER_FROM",
    # Exotel / custom telephony
    "EXOTEL_ACCOUNT_SID",
    "EXOTEL_API_KEY",
    "EXOTEL_API_TOKEN",
    "EXOPHONE",
    "EXOTEL_APP_ID",
    # EnableX
    "ENABLEX_APP_ID",
    "ENABLEX_APP_KEY",
    "ENABLEX_FROM_NUMBER",
    # Plivo
    "PLIVO_AUTH_ID",
    "PLIVO_AUTH_TOKEN",
    "PLIVO_PHONE_NUMBER",
    # Vobiz
    "VOBIZ_AUTH_ID",
    "VOBIZ_AUTH_TOKEN",
    "VOBIZ_PHONE_NUMBER",
    # Human handoff / warm transfer
    "WARM_TRANSFER_NUMBER",
    "WARM_TRANSFER_NAME",
    # STT
    "DEEPGRAM_API_KEY",
    "SARVAM_API_KEY",
    "DEEPGRAM_STT_MODEL",
    "CARTESIA_STT_MODEL",
    "SARVAM_STT_MODEL",
    "ELEVENLABS_STT_MODEL",
    "DEEPGRAM_VOICE",
    "SARVAM_VOICE_ID",
    "SMALLEST_STT_MODEL",
    "SMALLEST_VOICE_ID",
    "ASSEMBLYAI_API_KEY",
    "ASSEMBLYAI_STT_MODEL",
    "GLADIA_API_KEY",
    "GLADIA_STT_MODEL",
    "RINGG_AI_API_KEY",
    "RINGG_AI_STT_MODEL",
    "INWORLD_API_KEY",
    "INWORLD_STT_MODEL",
    "AZURE_SPEECH_API_KEY",
    "AZURE_SPEECH_API_VERSION",
    "AZURE_SPEECH_REGION",
    "AZURE_STT_MODEL",
    "AZURE_SPEECH_ENDPOINT",
    "VACHANA_API_KEY",
    "VACHANA_STT_MODEL",
    # TTS
    "CARTESIA_API_KEY",
    "ELEVENLABS_API_KEY",
    "MIMO_API_KEY",
    "CARTESIA_VOICE_ID",
    "ELEVENLABS_VOICE_ID",
    "MIMO_VOICE_ID",
    "DEEPGRAM_TTS_MODEL",
    "ELEVENLABS_TTS_MODEL",
    "MIMO_TTS_MODEL",
    "SARVAM_TTS_MODEL",
    "CARTESIA_TTS_MODEL",
    "MISTRAL_TTS_MODEL",
    "SMALLEST_API_KEY",
    "SMALLEST_TTS_MODEL",
    "INWORLD_TTS_MODEL",
    "INWORLD_VOICE_ID",
    "RIME_API_KEY",
    "RIME_TTS_MODEL",
    "RIME_VOICE_ID",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_DEFAULT_REGION",
    "POLLY_TTS_MODEL",
    "POLLY_VOICE_ID",
    "AZURE_TTS_MODEL",
    "AZURE_VOICE_ID",
    "KITTEN_TTS_MODEL",
    "KITTEN_TTS_VOICE",
    "MISTRAL_VOICE_ID",
    "VACHANA_TTS_MODEL",
    "VACHANA_VOICE_ID",
    # LLM
    "OPENAI_API_KEY",
    "MISTRAL_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "PERPLEXITY_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
    "MIMO_MODEL",
    "MISTRAL_MODEL",
    "OPENAI_MODEL",
    "GEMINI_MODEL",
    "ANTHROPIC_MODEL",
    "PERPLEXITY_MODEL",
    "OPENROUTER_MODEL",
    "CEREBRAS_MODEL",
    "SARVAM_MODEL",
    "GROQ_STT_MODEL",
    "GROQ_TTS_MODEL",
    "GROQ_VOICE",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "AZURE_LLM_API_KEY",
    "AZURE_LLM_ENDPOINT",
    "AZURE_LLM_API_VERSION",
    "AZURE_LLM_REGION",
    "AZURE_LLM_MODEL",
    "SMALLEST_LLM_MODEL",
    "AIRLLM_MODEL",
    "AIRLLM_COMPRESSION",
    "AIRLLM_MAX_NEW_TOKENS",
    "INWORLD_LLM_MODEL",
    # Email / SMTP
    "SMTP_SERVER",
    "SMTP_PORT",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "SMTP_FROM_EMAIL",
    # Email / IMAP (inbound polling)
    "IMAP_SERVER",
    "IMAP_PORT",
    "IMAP_USERNAME",
    "IMAP_PASSWORD",
    # Enrichment
    "APOLLO_API_KEY",
    "LUSHA_API_KEY",
    "ZOOMINFO_CLIENT_ID",
    "ZOOMINFO_API_KEY",
    "API_LAYER_API_KEY",
    "TRUECALLER_KEY_ID",
    "TRUECALLER_API_KEY",
    "TRUECALLER_CLIENT_ACCOUNT_ID"
}

SECRET_INTEGRATION_KEYS = {
    "TWILIO_ACCOUNT_SID",
    "TWILIO_AUTH_TOKEN",
    "EXOTEL_API_KEY",
    "EXOTEL_API_TOKEN",
    "ENABLEX_APP_KEY",
    "DEEPGRAM_API_KEY",
    "SARVAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "CARTESIA_API_KEY",
    "MIMO_API_KEY",
    "MISTRAL_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "PERPLEXITY_API_KEY",
    "CEREBRAS_API_KEY",
    "OPENROUTER_API_KEY",
    "OPENAI_API_KEY",
    "SMTP_PASSWORD",
    "SMTP_USERNAME",
    "IMAP_PASSWORD",
    "IMAP_USERNAME",
    "SMALLEST_API_KEY",
    "APOLLO_API_KEY",
    "LUSHA_API_KEY",
    "ZOOMINFO_CLIENT_ID",
    "ZOOMINFO_API_KEY",
    "GROQ_API_KEY",
    "VACHANA_API_KEY",
    "PLIVO_AUTH_TOKEN",
    "VOBIZ_AUTH_TOKEN",
    "ASSEMBLYAI_API_KEY",
    "GLADIA_API_KEY",
    "RINGG_AI_API_KEY",
    "RIME_API_KEY",
    "INWORLD_API_KEY",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AZURE_LLM_API_KEY",
    "AZURE_SPEECH_API_KEY",
    "API_LAYER_API_KEY",
    "TRUECALLER_KEY_ID",
    "TRUECALLER_API_KEY",
    "TRUECALLER_CLIENT_ACCOUNT_ID"
}

PLAIN_INTEGRATION_KEYS = ALL_INTEGRATION_KEYS - SECRET_INTEGRATION_KEYS

_USER_PERSONAL_KEYS = {"SYSTEM_PROMPT", "AI_VERBOSITY", "WARM_TRANSFER_NUMBER", "WARM_TRANSFER_NAME"}

_USER_EMAIL_KEYS = [
    "SMTP_HOST", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_FROM_EMAIL",
    "IMAP_SERVER", "IMAP_PORT", "IMAP_SECURITY", "IMAP_USERNAME", "IMAP_PASSWORD",
]
_USER_EMAIL_SECRET_KEYS = {"SMTP_PASSWORD", "IMAP_PASSWORD", "SMTP_USERNAME", "IMAP_USERNAME"}


# Company Settings

@router.get("/company-settings")
async def get_company_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    settings = session.exec(
        select(CompanySetting).where(CompanySetting.company_id == current_user.company_id)
    ).all()
    return {item.key: "***MASKED***" if item.is_secret else item.value for item in settings}


@router.get('/company-prompts')
async def list_company_prompts(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    prompts = session.exec(
        select(CompanyPrompt).where(CompanyPrompt.company_id == current_user.company_id).order_by(CompanyPrompt.version.desc())
    ).all()
    return [
        {
            "id": p.id,
            "version": p.version,
            "prompt_text": p.prompt_text,
            "author_id": p.author_id,
            "change_reason": p.change_reason,
            "is_active": p.is_active,
            "published_at": p.published_at.isoformat() if p.published_at else None,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        }
        for p in prompts
    ]


from pydantic import BaseModel

class CompanyPromptCreate(BaseModel):
    prompt_text: str
    change_reason: str | None = None

@router.post('/company-prompts')
async def create_company_prompt(
    body: CompanyPromptCreate,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):

    last = session.exec(select(CompanyPrompt.version).where(CompanyPrompt.company_id == current_user.company_id).order_by(CompanyPrompt.version.desc()).limit(1)).first()
    next_version = (last or 0) + 1
    prompt = CompanyPrompt(
        company_id=current_user.company_id,
        version=next_version,
        prompt_text=body.prompt_text,
        author_id=current_user.id,
        change_reason=body.change_reason,
        is_active=False,
        published_at=None,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return {"id": prompt.id, "version": prompt.version}


@router.post('/company-prompts/{prompt_id}/activate')
async def activate_company_prompt(
    prompt_id: int,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    prompt = session.get(CompanyPrompt, prompt_id)
    if not prompt or prompt.company_id != current_user.company_id:
        raise HTTPException(status_code=404, detail="Prompt not found")
    # Deactivate other versions for this company
    other_prompts = session.exec(select(CompanyPrompt).where(CompanyPrompt.company_id == current_user.company_id, CompanyPrompt.is_active == True)).all()
    for p in other_prompts:
        p.is_active = False
        session.add(p)

    prompt.is_active = True
    prompt.published_at = utc_now()
    session.add(prompt)
    session.commit()
    return {"status": "activated", "id": prompt.id}


@router.patch("/company-settings")
async def upsert_company_settings(
    payload: CompanySettingsBulkUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("settings.manage_company")),
):
    for item in payload.items:
        existing = session.exec(
            select(CompanySetting).where(
                CompanySetting.company_id == current_user.company_id,
                CompanySetting.key == item.key,
            )
        ).first()

        stored_value = encrypt_value(item.value) if item.is_secret else item.value
        if existing:
            existing.value = stored_value
            existing.is_secret = item.is_secret
            existing.updated_at = utc_now()
            existing.updated_by = current_user.id
            session.add(existing)
        else:
            session.add(
                CompanySetting(
                    company_id=current_user.company_id,
                    key=item.key,
                    value=stored_value,
                    is_secret=item.is_secret,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
            )

    session.commit()
    _sc.invalidate_user(current_user.company_id)

    _PROVIDER_MAPPING = {
        "LLM_PROVIDER": "llm_provider",
        "STT_PROVIDER": "stt_provider",
        "TTS_PROVIDER": "tts_provider",
    }
    changed_provider_cols = [
        col for key, col in _PROVIDER_MAPPING.items()
        if any(item.key == key for item in payload.items)
    ]
    if changed_provider_cols:
        from models.models import VoiceAgentRuntimeConfig as _VARConfig
        runtimes = session.exec(
            select(_VARConfig).where(_VARConfig.company_id == current_user.company_id)
        ).all()
        for rt in runtimes:
            for col in changed_provider_cols:
                setattr(rt, col, None)
            session.add(rt)
        session.commit()

    return {"message": "Company settings updated"}


# Company Integrations

@router.get("/company-integrations")
async def get_company_integrations(
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("integrations.read_company")),
):
    settings = session.exec(
        select(CompanySetting).where(
            CompanySetting.company_id == current_user.company_id,
            CompanySetting.key.in_(ALL_INTEGRATION_KEYS | {"SMTP_HOST"}),
        )
    ).all()

    result: dict[str, str] = {}
    for item in settings:
        result_key = "SMTP_SERVER" if item.key == "SMTP_HOST" else item.key

        if item.is_secret:
            raw = decrypt_value(item.value)
            if raw and len(raw) > 8:
                result[result_key] = raw[:3] + "..." + raw[-4:]
            else:
                result[result_key] = "***" if raw else ""
        else:
            result[result_key] = item.value

    if "SMTP_HOST" in result and "SMTP_SERVER" not in result:
        result["SMTP_SERVER"] = result["SMTP_HOST"]

    return result


@router.patch("/company-integrations")
async def update_company_integrations(
    payload: CompanySettingsBulkUpsert,
    session: Session = Depends(get_session),
    current_user: User = Depends(PermissionChecker("integrations.manage_company")),
):
    allowed_keys = SECRET_INTEGRATION_KEYS | PLAIN_INTEGRATION_KEYS | {"SMTP_HOST", "SMTP_SERVER"}

    import logging
    _log = logging.getLogger(__name__)
    _log.warning("[INTEGRATION PATCH] payload has %d items", len(payload.items))

    for item in payload.items:
        if item.key not in allowed_keys:
            _log.warning("[INTEGRATION PATCH] SKIP (not allowed): key=%s", item.key)
            continue

        normalized_key = "SMTP_HOST" if item.key == "SMTP_SERVER" else item.key
        value = item.value.strip()
        if not value:
            _log.warning("[INTEGRATION PATCH] SKIP (empty): key=%s", normalized_key)
            continue
        if value == "***MASKED***" or "..." in value:
            _log.warning("[INTEGRATION PATCH] SKIP (masked): key=%s value=%.20s", normalized_key, value)
            continue

        _log.warning("[INTEGRATION PATCH] SAVE: key=%s is_secret=%s value_len=%d", normalized_key, normalized_key in SECRET_INTEGRATION_KEYS, len(value))

        is_secret = normalized_key in SECRET_INTEGRATION_KEYS
        stored_value = encrypt_value(value) if is_secret else value
        existing = session.exec(
            select(CompanySetting).where(
                CompanySetting.company_id == current_user.company_id,
                CompanySetting.key == normalized_key,
            )
        ).first()

        if existing:
            old_val = existing.value
            if old_val != stored_value and normalized_key in ("ASR_STORE_RAW_JSON", "ASR_OVERLAP_THRESHOLD"):
                # record audit row for sensitive ASR setting changes
                try:
                    audit = CompanySettingAudit(
                        company_id=current_user.company_id,
                        key=normalized_key,
                        old_value=str(old_val) if old_val is not None else None,
                        new_value=str(stored_value) if stored_value is not None else None,
                        changed_by=current_user.id,
                    )
                    session.add(audit)
                except Exception:
                    # never raise to caller on audit failure
                    import logging as _logging
                    _logging.getLogger(__name__).exception("Failed to write CompanySettingAudit")
            existing.value = stored_value
            existing.is_secret = is_secret
            existing.updated_at = utc_now()
            existing.updated_by = current_user.id
            session.add(existing)
        else:
            session.add(
                CompanySetting(
                    company_id=current_user.company_id,
                    key=normalized_key,
                    value=stored_value,
                    is_secret=is_secret,
                    created_by=current_user.id,
                    updated_by=current_user.id,
                )
            )
            if normalized_key in ("ASR_STORE_RAW_JSON", "ASR_OVERLAP_THRESHOLD"):
                try:
                    audit = CompanySettingAudit(
                        company_id=current_user.company_id,
                        key=normalized_key,
                        old_value=None,
                        new_value=str(stored_value) if stored_value is not None else None,
                        changed_by=current_user.id,
                    )
                    session.add(audit)
                except Exception:
                    import logging as _logging
                    _logging.getLogger(__name__).exception("Failed to write CompanySettingAudit")


    session.commit()
    _sc.invalidate_user(current_user.company_id)
    return {"message": "Company integrations updated"}


# User Personal Settings

@router.get("/me/settings")
async def get_my_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the calling user's personal AI/preference settings."""
    from credentials_service import get_user_setting_value
    return {key: get_user_setting_value(session, current_user.id, key) or "" for key in _USER_PERSONAL_KEYS}


@router.put("/me/settings")
async def save_my_settings(
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Save the calling user's personal AI/preference settings."""
    from credentials_service import save_user_setting
    for key, value in data.items():
        if key in _USER_PERSONAL_KEYS and isinstance(value, str):
            save_user_setting(session, current_user.id, key, value)
    session.commit()
    return {"status": "saved"}


@router.get("/me/email-settings")
async def get_my_email_settings(
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Return the calling user's personal email settings."""
    from credentials_service import get_user_setting_value
    result: dict[str, str] = {}
    for key in _USER_EMAIL_KEYS:
        val = get_user_setting_value(session, current_user.id, key) or ""
        if val and key in _USER_EMAIL_SECRET_KEYS:
            result[key] = "***" + val[-4:] if len(val) > 4 else "***"
        else:
            result[key] = val
    return result


@router.put("/me/email-settings")
async def save_my_email_settings(
    data: dict,
    session: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
):
    """Save the calling user's personal email settings."""
    from credentials_service import save_user_setting
    for key, value in data.items():
        if key in _USER_EMAIL_KEYS and isinstance(value, str) and value and not value.startswith("***"):
            save_user_setting(session, current_user.id, key, value)
    session.commit()
    return {"status": "saved"}


def _mask_debug_value(key: str, value: str) -> str:
    """Mask likely secret values in debug output."""
    if not value:
        return ""
    upper = key.upper()
    secretish = (
        key in SECRET_INTEGRATION_KEYS
        or "PASSWORD" in upper
        or "SECRET" in upper
        or "TOKEN" in upper
        or "API_KEY" in upper
        or upper.endswith("_KEY")
    )
    if not secretish:
        return value
    if len(value) <= 8:
        return "***MASKED***"
    return value[:3] + "..." + value[-3:]


@router.get("/debug/settings-cache/{company_id}")
async def debug_settings_cache(
    company_id: int,
    include_values: bool = Query(default=False, description="Include cached values (secrets are masked)"),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
):
    """
    Debug endpoint to inspect in-process settings cache for the current company.
    Useful to verify cache warm/cold behavior during call setup.
    """
    if company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="You can only inspect your own company cache")

    loaded = _sc.get("__cache_loaded__", user_id=company_id) is not None
    items = _sc.get_all(user_id=company_id)
    items.pop("__cache_loaded__", None)
    keys = sorted(items.keys())

    response: dict = {
        "company_id": company_id,
        "cache_loaded": loaded,
        "entry_count": len(keys),
        "keys": keys,
    }

    if include_values:
        response["values"] = {k: _mask_debug_value(k, str(v)) for k, v in items.items()}

    return response


@router.get("/debug/groq-capabilities/{company_id}")
async def debug_groq_capabilities(
    company_id: int,
    run_probe: bool = Query(default=False, description="Run live Groq API probes for chat/stt/tts"),
    current_user: User = Depends(PermissionChecker("settings.read_company")),
    session: Session = Depends(get_session),
):
    """
    Debug endpoint for Groq readiness + optional live probes.
    """
    if company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="You can only inspect your own company capabilities")

    from credentials_service import get_company_setting_value

    groq_api_key = get_company_setting_value(session, company_id, "GROQ_API_KEY")
    chat_model = (
        get_company_setting_value(session, company_id, "GROQ_MODEL")
        or "llama-3.1-8b-instant"
    )
    stt_model = (
        get_company_setting_value(session, company_id, "GROQ_STT_MODEL")
        or "whisper-large-v3-turbo"
    )
    tts_model = (
        get_company_setting_value(session, company_id, "GROQ_TTS_MODEL")
        or "canopylabs/orpheus-v1-english"
    )
    tts_voice = (
        get_company_setting_value(session, company_id, "GROQ_VOICE")
        or "troy"
    )

    sdk_info: dict = {"available": False}
    try:
        import groq as _groq
        from groq import Groq as _Groq
        sdk_info = {
            "available": True,
            "version": getattr(_groq, "__version__", "unknown"),
            "has_groq_client": hasattr(_groq, "Groq"),
            "has_async_client": hasattr(_groq, "AsyncGroq"),
        }
        if groq_api_key:
            c = _Groq(api_key=groq_api_key)
            sdk_info["has_chat_completions"] = hasattr(c.chat, "completions") and hasattr(c.chat.completions, "create")
            sdk_info["has_audio_transcriptions"] = hasattr(c, "audio") and hasattr(c.audio, "transcriptions")
            sdk_info["has_audio_speech"] = hasattr(c, "audio") and hasattr(c.audio, "speech")
    except Exception as exc:
        sdk_info = {"available": False, "error": str(exc)}

    response: dict = {
        "company_id": company_id,
        "configured": {
            "groq_api_key_present": bool(groq_api_key),
            "groq_api_key_masked": _mask_debug_value("GROQ_API_KEY", groq_api_key or ""),
            "chat_model": chat_model,
            "stt_model": stt_model,
            "tts_model": tts_model,
            "tts_voice": tts_voice,
        },
        "sdk": sdk_info,
        "probe_run": run_probe,
    }

    if not run_probe:
        return response

    probes: dict = {
        "chat": {"ok": False, "error": None},
        "tts": {"ok": False, "error": None},
        "stt": {"ok": False, "error": None},
    }

    if not groq_api_key:
        probes["chat"]["error"] = "GROQ_API_KEY not configured"
        probes["tts"]["error"] = "GROQ_API_KEY not configured"
        probes["stt"]["error"] = "GROQ_API_KEY not configured"
        response["probes"] = probes
        return response

    try:
        import asyncio
        import io
        import wave
        from groq import Groq

        client = Groq(api_key=groq_api_key)

        # Chat probe
        try:
            def _chat_probe():
                return client.chat.completions.create(
                    model=chat_model,
                    messages=[
                        {"role": "system", "content": "You are a concise assistant."},
                        {"role": "user", "content": "Reply with exactly OK"},
                    ],
                    max_completion_tokens=16,
                    temperature=0,
                )

            chat_resp = await asyncio.to_thread(_chat_probe)
            msg = ""
            if getattr(chat_resp, "choices", None):
                first = chat_resp.choices[0]
                msg = getattr(getattr(first, "message", None), "content", "") or ""
            probes["chat"]["ok"] = bool(msg.strip())
            probes["chat"]["sample"] = msg.strip()[:80]
        except Exception as exc:
            probes["chat"]["error"] = str(exc)

        # TTS probe (small payload)
        try:
            def _tts_probe():
                return client.audio.speech.create(
                    model=tts_model,
                    voice=tts_voice,
                    input="Hello from Rio.",
                    response_format="mulaw",
                    sample_rate=8000,
                )

            tts_resp = await asyncio.to_thread(_tts_probe)
            tts_bytes = await asyncio.to_thread(tts_resp.read)
            probes["tts"]["ok"] = bool(tts_bytes)
            probes["tts"]["bytes"] = len(tts_bytes or b"")
        except Exception as exc:
            probes["tts"]["error"] = str(exc)

        # STT probe (0.5s silence wav)
        try:
            wav_buf = io.BytesIO()
            with wave.open(wav_buf, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(b"\x00\x00" * 8000)

            file_obj = ("silence.wav", wav_buf.getvalue())

            def _stt_probe():
                return client.audio.transcriptions.create(
                    model=stt_model,
                    file=file_obj,
                    response_format="verbose_json",
                    language="en",
                )

            stt_resp = await asyncio.to_thread(_stt_probe)
            transcript = getattr(stt_resp, "text", None)
            if transcript is None and isinstance(stt_resp, dict):
                transcript = stt_resp.get("text")
            probes["stt"]["ok"] = transcript is not None
            probes["stt"]["sample"] = (transcript or "")[:80]
        except Exception as exc:
            probes["stt"]["error"] = str(exc)

    except Exception as exc:
        probes["chat"]["error"] = probes["chat"]["error"] or f"Probe init error: {exc}"
        probes["tts"]["error"] = probes["tts"]["error"] or f"Probe init error: {exc}"
        probes["stt"]["error"] = probes["stt"]["error"] or f"Probe init error: {exc}"

    response["probes"] = probes
    return response
