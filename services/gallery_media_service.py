"""Store and serve gallery image uploads (videos are no longer accepted)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage" / "gallery_media"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
# Kept only so existing stored videos can still be served.
LEGACY_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".m4v": "video/x-m4v",
}


def _safe_filename(name: str) -> str:
    base = Path(name or "media").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "media"


def media_type_for_ext(ext: str) -> str:
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in LEGACY_VIDEO_EXTENSIONS:
        return "video"
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported file type")


async def save_gallery_media(school_id: str, file: UploadFile) -> dict:
    original = _safe_filename(file.filename or "media")
    ext = Path(original).suffix.lower()
    if ext in LEGACY_VIDEO_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Videos are not allowed in the gallery. Upload an image instead.",
        )
    if ext not in ALLOWED_EXTENSIONS:
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
    dest = folder / stored_name
    dest.write_bytes(content)

    return {
        "media_type": "image",
        "file_url": f"/api/gallery/files/{stored_name}",
        "file_name": original,
        "content_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
        "stored_name": stored_name,
    }


def delete_gallery_file(school_id: str, filename: str) -> None:
    path, _ = resolve_gallery_file(school_id, filename)
    path.unlink(missing_ok=True)


def filename_from_file_url(file_url: str) -> str:
    return Path(file_url.rstrip("/")).name


def resolve_gallery_file(school_id: str, filename: str) -> tuple[Path, str]:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    path = STORAGE_DIR / school_id / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    ext = path.suffix.lower()
    return path, MIME_BY_EXT.get(ext, "application/octet-stream")
