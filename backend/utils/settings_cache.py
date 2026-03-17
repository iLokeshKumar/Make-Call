import logging
from typing import Dict, Optional
from sqlmodel import Session, select
from models.models import SystemSettings

logger = logging.getLogger(__name__)

# Module-level cache — lives for the entire process lifetime
_cache: Dict[str, str] = {}
_loaded: bool = False


def load(session: Session) -> None:
    """Load all SystemSettings from DB into memory with decryption. Call once at startup."""
    global _cache, _loaded
    from utils.encryption import decrypt_value
    settings = session.exec(select(SystemSettings)).all()
    # We store decrypted values in memory for easy access throughout the app
    _cache = {s.key: decrypt_value(s.value) for s in settings}
    _loaded = True
    logger.info(f"✅ SettingsCache loaded and decrypted: {len(_cache)} keys")


def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a setting from cache."""
    return _cache.get(key, default)


def get_all() -> Dict[str, str]:
    """Return a shallow copy of all settings."""
    return dict(_cache)


def set(key: str, value: str) -> None:
    """Update a single key in cache with decryption."""
    from utils.encryption import decrypt_value
    _cache[key] = decrypt_value(value)


def update(data: Dict[str, str]) -> None:
    """Bulk update cache keys with decryption."""
    from utils.encryption import decrypt_value
    for k, v in data.items():
        _cache[k] = decrypt_value(v)
    logger.debug(f"SettingsCache updated and decrypted: {list(data.keys())}")


def is_loaded() -> bool:
    return _loaded