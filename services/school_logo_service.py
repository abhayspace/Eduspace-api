"""Store and serve school logo uploads."""
from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from fastapi import HTTPException, status

ROOT_DIR = Path(__file__).resolve().parent.parent
STORAGE_DIR = ROOT_DIR / "storage" / "school_logos"
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_BYTES = 5 * 1024 * 1024
MIME_BY_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _safe_ext(filename: str | None, content_type: str | None) -> str:
    name = Path(filename or "").name
    ext = Path(name).suffix.lower()
    if ext in ALLOWED_EXTENSIONS:
        return ext
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }
    guessed = mapping.get((content_type or "").lower(), "")
    if guessed in ALLOWED_EXTENSIONS:
        return guessed
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Allowed logo types: JPG, PNG, WEBP",
    )


def save_school_logo_bytes(
    school_id: str,
    content: bytes,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty logo file")
    if len(content) > MAX_BYTES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Logo must be 5 MB or smaller")

    ext = _safe_ext(filename, content_type)
    stored_name = f"{uuid.uuid4().hex}{ext}"
    folder = STORAGE_DIR / school_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / stored_name
    dest.write_bytes(content)
    return f"/api/schools/{school_id}/logo/{stored_name}"


def save_school_logo_base64(
    school_id: str,
    logo_base64: str,
    *,
    filename: str | None = None,
    content_type: str | None = None,
) -> str:
    raw = (logo_base64 or "").strip()
    if not raw:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty logo data")

    # Accept data-URL or bare base64.
    if "," in raw and raw.lower().startswith("data:"):
        header, raw = raw.split(",", 1)
        match = re.search(r"data:([^;]+);base64", header, flags=re.I)
        if match and not content_type:
            content_type = match.group(1)

    try:
        content = base64.b64decode(raw, validate=False)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid logo data") from exc

    return save_school_logo_bytes(
        school_id,
        content,
        filename=filename,
        content_type=content_type,
    )


def resolve_school_logo(school_id: str, filename: str) -> tuple[Path, str]:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid filename")
    path = STORAGE_DIR / school_id / safe
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Logo not found")
    ext = path.suffix.lower()
    return path, MIME_BY_EXT.get(ext, "application/octet-stream")
