import os
import uuid
import logging
from fastapi import UploadFile

logger = logging.getLogger(__name__)

UPLOAD_DIR = os.path.join(os.getcwd(), "uploads", "avatars")

def save_avatar(file: UploadFile) -> str:
    """Saves an uploaded avatar to the filesystem and returns the relative URL."""
    if not os.path.exists(UPLOAD_DIR):
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        logger.info(f"📁 Created upload directory: {UPLOAD_DIR}")

    # Generate unique filename
    ext = os.path.splitext(file.filename)[1]
    filename = f"{uuid.uuid4().hex}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    with open(file_path, "wb") as buffer:
        buffer.write(file.file.read())

    # Return the URL path (relative to the server)
    return f"/uploads/avatars/{filename}"
