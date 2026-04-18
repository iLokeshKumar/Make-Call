from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from auth import PermissionChecker, get_current_user
from database import get_session
from models.models import CompanySetting, CompanySettingsBulkUpsert, User, utc_now
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
}

SECRET_INTEGRATION_KEYS = {
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
}

PLAIN_INTEGRATION_KEYS = ALL_INTEGRATION_KEYS - SECRET_INTEGRATION_KEYS

_USER_PERSONAL_KEYS = {"SYSTEM_PROMPT", "AI_VERBOSITY"}

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
