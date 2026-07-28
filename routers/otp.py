"""OTP routes for email verification during school registration."""
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from services.email_service import send_email, sending_domain, _from_address
from services.otp_service import generate_and_store, is_verified, verify

router = APIRouter(prefix="/auth/otp", tags=["otp"])
logger = logging.getLogger("eduspace.otp")


class OtpSendIn(BaseModel):
    email: EmailStr
    purpose: str = "register"


class OtpVerifyIn(BaseModel):
    email: EmailStr
    otp: str
    purpose: str = "register"


_ALLOWED_OTP_PURPOSES = {"register", "school_profile_email"}


def _otp_email_body(otp: str) -> str:
    return (
        f"Your EduSpace Email Verification Code\n"
        f"{'=' * 42}\n\n"
        f"Your one-time verification code is:\n\n"
        f"    {otp}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you did not request this code, please ignore this email.\n"
        f"Your school registration is not complete until you verify your email.\n\n"
        f"— The EduSpace Team\n"
    )


def _normalize_purpose(purpose: str) -> str:
    value = (purpose or "register").strip().lower()
    if value not in _ALLOWED_OTP_PURPOSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OTP purpose")
    return value


@router.post("/send", status_code=status.HTTP_200_OK)
async def send_otp(body: OtpSendIn) -> dict:
    purpose = _normalize_purpose(body.purpose)
    otp = generate_and_store(body.email, purpose=purpose)
    sent = await send_email(
        body.email,
        "EduSpace – Your Email Verification Code",
        _otp_email_body(otp),
    )
    if not sent:
        domain = sending_domain()
        logger.warning(
            "OTP email could not be delivered to %s (from=%s). Check RESEND_API_KEY "
            "and that domain %s is verified in the Resend dashboard.",
            body.email,
            _from_address(),
            domain,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not send verification email. "
            f"Confirm Resend API key is set and that the sending domain "
            f"({domain}) is verified in the Resend dashboard.",
        )
    return {"message": "OTP sent. Please check your inbox (and Spam/Junk folder)."}


@router.post("/verify", status_code=status.HTTP_200_OK)
async def verify_otp(body: OtpVerifyIn) -> dict:
    purpose = _normalize_purpose(body.purpose)
    if not verify(body.email, body.otp, purpose=purpose):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OTP. Please request a new one.")
    return {"verified": True, "email": body.email}


# ---------------------------------------------------------------------------
# Dev-only: expose OTP for automated testing.
# Only active when LOG_LEVEL=DEBUG. Never expose in production.
# ---------------------------------------------------------------------------
import os as _os

if _os.environ.get("LOG_LEVEL", "INFO").upper() == "DEBUG":
    from services.otp_service import _store as _otp_store

    @router.post("/dev-read", include_in_schema=False)
    async def dev_read_otp(body: OtpSendIn) -> dict:
        key = f"register:{body.email.lower()}"
        entry = _otp_store.get(key) or _otp_store.get(body.email.lower())
        if not entry:
            raise HTTPException(404, "No OTP for this email")
        return {"otp": entry["otp"]}
