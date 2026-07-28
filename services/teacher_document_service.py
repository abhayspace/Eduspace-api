"""Store and serve teacher document uploads (jpg, jpeg, png, pdf)."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage" / "teacher_documents"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_BYTES = 10 * 1024 * 1024
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}


def _safe_filename(name: str) -> str:
    base = Path(name or "document").name
    base = re.sub(r"[^A-Za-z0-9._-]", "_", base)
    return base or "document"


async def save_teacher_document(school_id: str, file: UploadFile) -> dict:
    original = _safe_filename(file.filename or "document")
    ext = Path(original).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Allowed file types: JPG, JPEG, PNG, PDF",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File must be 10 MB or smaller")

    stored_name = f"{uuid.uuid4().hex}{ext}"
    folder = STORAGE_DIR / school_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / stored_name
    dest.write_bytes(content)

    return {
        "document_url": f"/api/teachers/documents/{stored_name}",
        "document_name": original,
        "content_type": MIME_BY_EXT.get(ext, "application/octet-stream"),
    }


def delete_teacher_document(school_id: str, filename: str) -> None:
    path, _ = resolve_teacher_document(school_id, filename)
    path.unlink(missing_ok=True)


def resolve_teacher_document(school_id: str, filename: str) -> tuple[Path, str]:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    path = STORAGE_DIR / school_id / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    ext = path.suffix.lower()
    return path, MIME_BY_EXT.get(ext, "application/octet-stream")
