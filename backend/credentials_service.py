import logging
from sqlmodel import Session, select
from database import engine
from models.models import SystemSettings
from utils.encryption import encrypt_value, decrypt_value
from utils.logger import setup_logger
from utils import settings_cache

logger = setup_logger(__name__)

def get_credential(key: str, user_id: int | None = None) -> str | None:
    """
    Get a decrypted credential from SettingsCache.
    Falls back to global if user-specific is not found.
    """
    val = settings_cache.get(key, user_id)
    if val and val.strip():
        logger.info(f"🔑 [credentials] Found '{key}' for user {user_id}")
        return val
        
    logger.info(f"⚠️ [credentials] No value found for '{key}' (user: {user_id})")
    return None

def get_credential_smtp(key: str, user_id: int | None = None) -> str | None:
    """SMTP-specific: DB first, then .env fallback for bootstrap."""
    val = get_credential(key, user_id)
    if val:
        return val
    import os
    return os.getenv(key)

def set_credential(key: str, plaintext: str) -> None:
    """Encrypt and persist a credential to SystemSettings."""
    encrypted = encrypt_value(plaintext)
    with Session(engine) as session:
        # Update user 4 (lokesh) or global if no user exists
        setting = session.exec(
            select(SystemSettings).where(SystemSettings.key == key, SystemSettings.user_id != None)
        ).first() or session.exec(
            select(SystemSettings).where(SystemSettings.key == key)
        ).first()

        if setting:
            setting.value = encrypted
            session.add(setting)
            session.commit()
        else:
            # Create a global one if none exists
            new_s = SystemSettings(key=key, value=encrypted)
            session.add(new_s)
            session.commit()
            
    # Sync SettingsCache
    settings_cache.set_val(key, plaintext, user_id=None) # Default to global if not specified

def delete_credential(key: str) -> None:
    """Clear a credential value."""
    with Session(engine) as session:
        settings = session.exec(select(SystemSettings).where(SystemSettings.key == key)).all()
        for s in settings:
            s.value = ""
            session.add(s)
        session.commit()
    # Sync SettingsCache (could iterate over users, but usually global is enough)
    settings_cache.set_val(key, "", user_id=None)

def bust_cache() -> None:
    # SettingsCache doesn't have a broad bust_cache, but it reloads on load()
    pass