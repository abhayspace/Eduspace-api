"""Receipt PDF storage — local filesystem today, S3-ready interface."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

logger = logging.getLogger("eduspace.receipt.storage")

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
# Dev layout: backend/storage/receipts/{year}/{receipt_number}.pdf
# (Equivalent to uploads/receipts/...; kept under storage/ to match other modules.)
STORAGE_ROOT = ROOT_DIR / "storage" / "receipts"


class ReceiptStorage(Protocol):
    def save_pdf(self, *, year: int, receipt_number: str, content: bytes) -> tuple[str, str]:
        """Persist PDF. Returns (pdf_path, pdf_url)."""
        ...

    def read_pdf(self, pdf_path: str) -> bytes:
        ...

    def resolve_local_path(self, pdf_path: str) -> Path:
        ...


class LocalReceiptStorage:
    """Filesystem storage under backend/storage/receipts/{year}/."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or STORAGE_ROOT

    def save_pdf(self, *, year: int, receipt_number: str, content: bytes) -> tuple[str, str]:
        folder = self.root / str(year)
        folder.mkdir(parents=True, exist_ok=True)
        safe_name = Path(receipt_number).name.replace("/", "_")
        dest = folder / f"{safe_name}.pdf"
        dest.write_bytes(content)
        # Relative path stored in DB (portable across machines / S3 keys later)
        relative = f"{year}/{safe_name}.pdf"
        pdf_url = f"/api/receipts/files/{year}/{safe_name}.pdf"
        logger.info("receipt PDF saved path=%s bytes=%s", dest, len(content))
        return relative, pdf_url

    def read_pdf(self, pdf_path: str) -> bytes:
        path = self.resolve_local_path(pdf_path)
        return path.read_bytes()

    def resolve_local_path(self, pdf_path: str) -> Path:
        # pdf_path is relative like "2026/SMW-2026-000001.pdf"
        safe = Path(pdf_path)
        if ".." in safe.parts:
            raise ValueError("Invalid pdf_path")
        full = (self.root / safe).resolve()
        if not str(full).startswith(str(self.root.resolve())):
            raise ValueError("Invalid pdf_path")
        if not full.is_file():
            raise FileNotFoundError(pdf_path)
        return full


# Default singleton — swap for S3ReceiptStorage later without changing callers.
default_storage: ReceiptStorage = LocalReceiptStorage()
