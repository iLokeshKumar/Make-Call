import logging
from typing import Dict, Optional, Any
from sqlmodel import Session, select
from models.models import SystemSettings

logger = logging.getLogger(__name__)

# Module-level cache — nested by user_id
# None represents global settings
_cache: Dict[Optional[int], Dict[str, str]] = {}
_loaded: bool = False


def load(session: Session) -> None:
    """Load all SystemSettings from DB into memory with decryption. Call once at startup."""
    global _cache, _loaded
    from utils.encryption import decrypt_value
    settings = session.exec(select(SystemSettings)).all()
    
    new_cache = {}
    for s in settings:
        u_id = s.user_id
        if u_id not in new_cache:
            new_cache[u_id] = {}
        new_cache[u_id][s.key] = decrypt_value(s.value)
    
    _cache = new_cache
    _loaded = True
    logger.info(f"✅ SettingsCache loaded and decrypted for {len(_cache)} users (including global)")


def get(key: str, user_id: Optional[int] = None, default: Optional[str] = None) -> Optional[str]:
    """
    Read a setting from cache. 
    If user_id is provided, it checks user-specific settings first, then falls back to global (None).
    """
    # Check user-specific
    if user_id is not None:
        user_settings = _cache.get(user_id, {})
        if key in user_settings:
            return user_settings[key]
            
    # Fallback to global
    global_settings = _cache.get(None, {})
    return global_settings.get(key, default)


def get_all(user_id: Optional[int] = None) -> Dict[str, str]:
    """Return all settings applicable to a user (merged with global)."""
    # Start with global
    merged = dict(_cache.get(None, {}))
    
    # Override with user-specific
    if user_id is not None:
        merged.update(_cache.get(user_id, {}))
        
    return merged


def set_val(key: str, value: str, user_id: Optional[int] = None) -> None:
    """Update a single key in cache for a specific user (or global). Handles decryption."""
    from utils.encryption import decrypt_value
    if user_id not in _cache:
        _cache[user_id] = {}
    _cache[user_id][key] = decrypt_value(value)


def update(data: Dict[str, str], user_id: Optional[int] = None) -> None:
    """Bulk update cache keys for a specific user (or global). Handles decryption."""
    from utils.encryption import decrypt_value
    if user_id not in _cache:
        _cache[user_id] = {}
        
    for k, v in data.items():
        _cache[user_id][k] = decrypt_value(v)
    logger.debug(f"SettingsCache updated for user {user_id}: {list(data.keys())}")


def is_loaded() -> bool:
    return _loaded