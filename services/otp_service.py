"""In-memory OTP store for email verification (registration + forgot password).

Stores: "{purpose}:{email}" -> {otp, expires_at, verified}
TTL: 10 minutes.
"""
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import Dict

logger = logging.getLogger("eduspace.otp")

_OTP_TTL_MINUTES = 10
_OTP_LENGTH = 6

# key -> {"otp": str, "expires_at": datetime, "verified": bool}
_store: Dict[str, dict] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _key(email: str, purpose: str = "register") -> str:
    return f"{purpose}:{email.lower().strip()}"


def generate_and_store(email: str, purpose: str = "register") -> str:
    """Generate a new 6-digit OTP for an email and store it. Returns the OTP."""
    otp = "".join(secrets.choice(string.digits) for _ in range(_OTP_LENGTH))
    expires_at = _now() + timedelta(minutes=_OTP_TTL_MINUTES)
    key = _key(email, purpose)
    _store[key] = {"otp": otp, "expires_at": expires_at, "verified": False}
    logger.info("OTP generated for %s purpose=%s (expires %s)", email, purpose, expires_at.isoformat())
    return otp


def verify(email: str, otp: str, purpose: str = "register") -> bool:
    """Return True and mark verified if the OTP is correct and not expired."""
    key = _key(email, purpose)
    entry = _store.get(key)
    if not entry:
        return False
    if entry["otp"] != otp.strip():
        return False
    if _now() > entry["expires_at"]:
        del _store[key]
        return False
    entry["verified"] = True
    return True


def is_verified(email: str, purpose: str = "register") -> bool:
    """Return True if the email has a valid verified OTP in-store."""
    key = _key(email, purpose)
    entry = _store.get(key)
    if not entry:
        return False
    if _now() > entry["expires_at"]:
        del _store[key]
        return False
    return entry.get("verified", False)


def clear(email: str, purpose: str = "register") -> None:
    _store.pop(_key(email, purpose), None)
