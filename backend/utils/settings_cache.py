import time
from typing import Dict, Optional, Tuple

# (value, expires_at) — expires_at is a float epoch second, or None for no expiry
_CacheEntry = Tuple[str, Optional[float]]
_cache: Dict[Optional[int], Dict[str, _CacheEntry]] = {}

# Default TTL in seconds. Set to 0 to disable expiry.
DEFAULT_TTL: int = 300  # 5 minutes


def _is_expired(entry: _CacheEntry) -> bool:
    _, expires_at = entry
    return expires_at is not None and time.monotonic() > expires_at


def _make_entry(value: str, ttl: Optional[int] = DEFAULT_TTL) -> _CacheEntry:
    expires_at = (time.monotonic() + ttl) if ttl else None
    return (value, expires_at)


def load(session) -> None:
    return None


def get(key: str, user_id: Optional[int] = None, default: Optional[str] = None) -> Optional[str]:
    # Check user-scoped entry first
    if user_id is not None:
        entry = _cache.get(user_id, {}).get(key)
        if entry is not None and not _is_expired(entry):
            return entry[0]
    # Fall back to global entry
    entry = _cache.get(None, {}).get(key)
    if entry is not None and not _is_expired(entry):
        return entry[0]
    return default


def get_all(user_id: Optional[int] = None) -> Dict[str, str]:
    now = time.monotonic()
    merged: Dict[str, str] = {
        k: v for k, (v, exp) in _cache.get(None, {}).items()
        if exp is None or now <= exp
    }
    if user_id is not None:
        merged.update({
            k: v for k, (v, exp) in _cache.get(user_id, {}).items()
            if exp is None or now <= exp
        })
    return merged


def set_val(key: str, value: str, user_id: Optional[int] = None, ttl: Optional[int] = DEFAULT_TTL) -> None:
    if user_id not in _cache:
        _cache[user_id] = {}
    _cache[user_id][key] = _make_entry(value, ttl)


def update(data: Dict[str, str], user_id: Optional[int] = None, ttl: Optional[int] = DEFAULT_TTL) -> None:
    if user_id not in _cache:
        _cache[user_id] = {}
    for key, value in data.items():
        _cache[user_id][key] = _make_entry(value, ttl)


def invalidate(key: str, user_id: Optional[int] = None) -> None:
    """Remove a single key from the cache for the given user (or global if user_id is None)."""
    _cache.get(user_id, {}).pop(key, None)


def invalidate_user(user_id: Optional[int]) -> None:
    """Purge all cached entries for a given user scope."""
    _cache.pop(user_id, None)


def invalidate_all() -> None:
    """Clear the entire cache (e.g., after a bulk settings update)."""
    _cache.clear()


def is_loaded() -> bool:
    return True
