from typing import Dict, Optional

_cache: Dict[Optional[int], Dict[str, str]] = {}


def load(session) -> None:
    return None


def get(key: str, user_id: Optional[int] = None, default: Optional[str] = None) -> Optional[str]:
    if user_id is not None and key in _cache.get(user_id, {}):
        return _cache[user_id][key]
    return _cache.get(None, {}).get(key, default)


def get_all(user_id: Optional[int] = None) -> Dict[str, str]:
    merged = dict(_cache.get(None, {}))
    if user_id is not None:
        merged.update(_cache.get(user_id, {}))
    return merged


def set_val(key: str, value: str, user_id: Optional[int] = None) -> None:
    if user_id not in _cache:
        _cache[user_id] = {}
    _cache[user_id][key] = value


def update(data: Dict[str, str], user_id: Optional[int] = None) -> None:
    if user_id not in _cache:
        _cache[user_id] = {}
    _cache[user_id].update(data)


def is_loaded() -> bool:
    return True
