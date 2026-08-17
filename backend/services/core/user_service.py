import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import UploadFile

logger = logging.getLogger(__name__)

UPLOADS_ROOT = Path(os.getenv("UPLOADS_DIR", os.path.join(os.getcwd(), "uploads")))


def _dated_subdir(category: str) -> tuple[Path, str]:
    """
    Return (absolute_dir, relative_url_prefix) for today's date bucket.
    Structure: uploads/<category>/YYYY-MM/DD/
    e.g.       uploads/avatars/2026-04/07/
    """
    now = datetime.now(timezone.utc)
    month_dir = now.strftime("%Y-%m")
    day_dir   = now.strftime("%d")
    abs_dir   = UPLOADS_ROOT / category / month_dir / day_dir
    abs_dir.mkdir(parents=True, exist_ok=True)
    rel_prefix = f"/uploads/{category}/{month_dir}/{day_dir}"
    return abs_dir, rel_prefix


def save_avatar(file: UploadFile) -> str:
    """Save an uploaded avatar into uploads/avatars/YYYY-MM/DD/ and return the URL path."""
    ext = Path(file.filename or "").suffix or ".jpg"
    filename = f"{uuid.uuid4().hex}{ext}"
    abs_dir, rel_prefix = _dated_subdir("avatars")
    (abs_dir / filename).write_bytes(file.file.read())
    url = f"{rel_prefix}/{filename}"
    logger.info("Avatar saved: %s", url)
    return url
