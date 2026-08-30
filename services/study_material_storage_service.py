"""Store and serve study material file uploads."""
from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage" / "study_materials"
MAX_BYTES = 50 * 1024 * 1024  # 50 MB


def _safe_filename(name: str) -> str:
    base = Path(name or "file").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "file"


async def save_study_file(school_id: str, file: UploadFile) -> dict:
    original = _safe_filename(file.filename or "file")
    ext = Path(original).suffix.lower()

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be 50 MB or smaller")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    folder = STORAGE_DIR / school_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / stored_name
    dest.write_bytes(content)

    mime = file.content_type or mimetypes.guess_type(original)[0] or "application/octet-stream"
    return {
        "file_url": f"/api/study-material/files/{stored_name}",
        "file_name": original,
        "content_type": mime,
        "file_size": len(content),
    }


def delete_study_file(school_id: str, filename: str) -> None:
    path, _ = resolve_study_file(school_id, filename)
    path.unlink(missing_ok=True)


def filename_from_file_url(file_url: str) -> str:
    return Path(file_url.rstrip("/")).name


def resolve_study_file(school_id: str, filename: str) -> tuple[Path, str]:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    path = STORAGE_DIR / school_id / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return path, mime
