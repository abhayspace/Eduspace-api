"""Store and serve School Feed image uploads."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage" / "feed_media"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def _safe_filename(name: str) -> str:
    base = Path(name or "media").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "media"


async def save_feed_media(school_id: str, file: UploadFile) -> dict:
    original = _safe_filename(file.filename or "media")
    ext = Path(original).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Allowed types: JPG, JPEG, PNG, WEBP, GIF",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(content) > MAX_IMAGE_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be 10 MB or smaller")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    folder = STORAGE_DIR / school_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored_name).write_bytes(content)

    return {
        "file_url": f"/api/feed/files/{stored_name}",
        "file_name": original,
        "content_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
    }


def resolve_feed_file(school_id: str, filename: str) -> tuple[Path, str]:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    path = STORAGE_DIR / school_id / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    ext = path.suffix.lower()
    return path, MIME_BY_EXT.get(ext, "application/octet-stream")


def delete_feed_file(school_id: str, filename: str) -> None:
    safe = Path(filename).name
    path = STORAGE_DIR / school_id / safe
    path.unlink(missing_ok=True)
