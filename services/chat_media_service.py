"""Store and serve chat image/video/file uploads."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage" / "chat_media"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm", ".m4v"}
FILE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".csv",
    ".zip",
}
ALLOWED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | FILE_EXTENSIONS
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024
MAX_FILE_BYTES = 25 * 1024 * 1024
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
    ".pdf": "application/pdf",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".zip": "application/zip",
}


def _safe_filename(name: str) -> str:
    base = Path(name or "media").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "media"


def media_type_for_ext(ext: str) -> str:
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in FILE_EXTENSIONS:
        return "file"
    raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unsupported file type")


async def save_chat_media(school_id: str, file: UploadFile) -> dict:
    original = _safe_filename(file.filename or "media")
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Allowed: images, videos, PDF, DOC, XLS, PPT, TXT, CSV, ZIP",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")

    media_type = media_type_for_ext(ext)
    if media_type == "image":
        max_bytes = MAX_IMAGE_BYTES
    elif media_type == "video":
        max_bytes = MAX_VIDEO_BYTES
    else:
        max_bytes = MAX_FILE_BYTES
    if len(content) > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File must be {limit_mb} MB or smaller")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    folder = STORAGE_DIR / school_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stored_name).write_bytes(content)

    return {
        "media_type": media_type,
        "media_url": f"/api/messages/files/{stored_name}",
        "media_name": original,
        "content_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
    }


def resolve_chat_file(school_id: str, filename: str) -> tuple[Path, str]:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    path = STORAGE_DIR / school_id / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    ext = path.suffix.lower()
    return path, MIME_BY_EXT.get(ext, "application/octet-stream")


def filename_from_media_url(media_url: str) -> str:
    return Path(media_url.rstrip("/")).name


def delete_chat_file(school_id: str, filename: str) -> None:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        return
    path = STORAGE_DIR / school_id / safe
    path.unlink(missing_ok=True)


def chat_file_exists(school_id: str, filename: str) -> bool:
    """Check whether a chat media file still exists on the server."""
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        return False
    return (STORAGE_DIR / school_id / safe).is_file()


async def reupload_chat_video(school_id: str, filename: str, file: UploadFile) -> dict:
    """Re-upload a video file to restore it on the server (from a user's local cache)."""
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    ext = Path(safe).suffix.lower()
    if ext not in VIDEO_EXTENSIONS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Only video files can be re-uploaded")

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(content) > MAX_VIDEO_BYTES:
        limit_mb = MAX_VIDEO_BYTES // (1024 * 1024)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File must be {limit_mb} MB or smaller")

    folder = STORAGE_DIR / school_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / safe).write_bytes(content)

    return {
        "media_url": f"/api/messages/files/{safe}",
        "media_type": "video",
        "restored": True,
    }
