"""Encrypt/decrypt payment gateway secrets at rest."""
from __future__ import annotations

import base64
import hashlib
from functools import lru_cache
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

from config import get_settings

_PREFIX = "enc:v1:"


@lru_cache
def _fernet() -> Fernet:
    settings = get_settings()
    raw = (settings.payment_credentials_key or "").strip()
    if raw:
        try:
            return Fernet(raw.encode("utf-8"))
        except Exception:
            return Fernet(_derive_key(raw))
    secret = (settings.jwt_secret or "eduspace-dev-payment-key").strip()
    return Fernet(_derive_key(secret))


def _derive_key(material: str) -> bytes:
    digest = hashlib.sha256(material.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith(_PREFIX):
        return text
    token = _fernet().encrypt(text.encode("utf-8")).decode("utf-8")
    return f"{_PREFIX}{token}"


def decrypt_secret(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not text.startswith(_PREFIX):
        return text
    token = text[len(_PREFIX) :]
    try:
        return _fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken:
        return None


def mask_secret(value: Optional[str]) -> Optional[str]:
    plain = decrypt_secret(value) if value and str(value).startswith(_PREFIX) else value
    if not plain:
        return None
    if len(plain) <= 4:
        return "****"
    return f"{'*' * max(4, len(plain) - 4)}{plain[-4:]}"
