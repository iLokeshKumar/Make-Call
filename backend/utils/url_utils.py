from urllib.parse import urlparse


def normalize_base_url(raw_url: str | None, default: str = "https://localhost:8000") -> str:
    candidate = (raw_url or "").strip()
    if not candidate:
        candidate = default
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if parsed.scheme and parsed.netloc:
        base = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base = candidate
    return base.rstrip("/")
