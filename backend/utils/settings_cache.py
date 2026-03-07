import logging
from typing import Dict, Optional
from sqlmodel import Session, select
from models.models import SystemSettings

logger = logging.getLogger(__name__)

# Module-level cache — lives for the entire process lifetime
_cache: Dict[str, str] = {}
_loaded: bool = False


def load(session: Session) -> None:
    """Load all SystemSettings from DB into memory. Call once at startup."""
    global _cache, _loaded
    settings = session.exec(select(SystemSettings)).all()
    _cache = {s.key: s.value for s in settings}
    _loaded = True
    logger.info(f"✅ SettingsCache loaded: {len(_cache)} keys")


def get(key: str, default: Optional[str] = None) -> Optional[str]:
    """Read a setting from cache."""
    return _cache.get(key, default)


def get_all() -> Dict[str, str]:
    """Return a shallow copy of all settings."""
    return dict(_cache)


def set(key: str, value: str) -> None:
    """Update a single key in cache (call after DB write)."""
    _cache[key] = value


def update(data: Dict[str, str]) -> None:
    """Bulk update cache keys (call after PATCH /settings)."""
    _cache.update(data)
    logger.debug(f"SettingsCache updated: {list(data.keys())}")


def is_loaded() -> bool:
    return _loaded