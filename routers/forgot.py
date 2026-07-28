"""Forgot-password recovery via linked Gmail OTP (student, staff, school login)."""
import logging
import re

from fastapi import APIRouter, HTTPException, status

from database import get_client
from schemas.forgot import (
    SchoolForgotResetIn,
    SchoolForgotSendIn,
    SchoolForgotVerifyIn,
    StaffForgotResetIn,
    StaffForgotSendIn,
    StaffForgotVerifyIn,
    StudentForgotResetIn,
    StudentForgotSendIn,
    StudentForgotSendOut,
    StudentForgotVerifyIn,
)
from services.email_service import send_email, sending_domain, _from_address
from services.otp_service import clear, generate_and_store, is_verified, verify
from utils.security import hash_password

router = APIRouter(prefix="/auth/forgot", tags=["forgot-password"])
logger = logging.getLogger("eduspace.forgot")

_OTP_PURPOSE = "forgot"
_GMAIL_RE = re.compile(r"^[^+@]+(\+[^@]+)?@(gmail|googlemail)\.com$", re.IGNORECASE)
_STAFF_ROLES = {
    "teacher",
    "receptionist",
    "accountant",
    "librarian",
    "transport_manager",
    "hostel_warden",
    "hostel_manager",
    "school_doctor",
    "principal",
    "vice_principal",
}

NO_GMAIL_MESSAGE = (
    "No Gmail is linked to your account. Please contact your school for the password. "
    "After logging in, link your Gmail from Profile → Account Settings."
)


def is_gmail(email: str | None) -> bool:
    if not email:
        return False
    value = email.strip().lower()
    if value.endswith("@eduspace.local") or value.endswith("@eduspace.app"):
        return False
    return bool(_GMAIL_RE.match(value))


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    if len(local) <= 2:
        visible = local[:1] + "***"
    else:
        visible = local[:2] + "***"
    return f"{visible}@{domain}"


def _admission_match_clauses(ident: str) -> list[str]:
    ident = ident.strip()
    clauses = [f"admission_no.eq.{ident}"]
    if ident.isdigit():
        n = int(ident)
        for candidate in {ident, str(n), f"{n:04d}", f"{n:05d}"}:
            clauses.append(f"admission_no.eq.{candidate}")
    else:
        clauses.append(f"admission_no.eq.{ident.upper()}")
    return list(dict.fromkeys(clauses))


def _otp_email_body(otp: str, full_name: str) -> str:
    name = full_name.strip() or "there"
    return (
        f"EduSpace – Password Reset Code\n"
        f"{'=' * 36}\n\n"
        f"Hi {name},\n\n"
        f"Your one-time password reset code is:\n\n"
        f"    {otp}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you did not request a password reset, you can ignore this email.\n\n"
        f"— The EduSpace Team\n"
    )


async def _find_student(school_id: str, admission_no: str) -> dict | None:
    client = get_client()
    clauses = _admission_match_clauses(admission_no)
    res = (
        await client.table("users")
        .select("id,email,full_name,role,school_id,admission_no,user_code,is_active")
        .eq("school_id", school_id)
        .eq("role", "student")
        .or_(",".join(clauses))
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def _find_staff(school_id: str, user_id: str) -> dict | None:
    client = get_client()
    code = user_id.strip().upper()
    res = (
        await client.table("users")
        .select("id,email,full_name,role,school_id,admission_no,user_code,is_active")
        .eq("school_id", school_id)
        .eq("user_code", code)
        .in_("role", list(_STAFF_ROLES))
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def _find_school_portal(school_id: str, account_type: str) -> dict | None:
    prefix = "SCH" if account_type == "office_staff" else "ADM"
    client = get_client()
    res = (
        await client.table("users")
        .select("id,email,full_name,role,school_id,admission_no,user_code,is_active")
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .like("user_code", f"{prefix}%")
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def _sync_school_management_passwords(school_id: str, new_password: str) -> None:
    """Reset the School Management (SCH) password. Also updates legacy ADM rows if present."""
    client = get_client()
    payload = {
        "password_hash": hash_password(new_password),
        "login_password": new_password,
        "must_change_password": False,
    }
    await (
        client.table("users")
        .update(payload)
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .like("user_code", "SCH%")
        .execute()
    )
    # Keep legacy ADM hashes aligned so forgotten dual-account schools stay usable.
    await (
        client.table("users")
        .update(payload)
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .like("user_code", "ADM%")
        .execute()
    )


async def _send_forgot_otp(user: dict) -> StudentForgotSendOut:
    email = (user.get("email") or "").strip().lower()
    if not is_gmail(email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_GMAIL_LINKED", "message": NO_GMAIL_MESSAGE},
        )

    otp = generate_and_store(email, purpose=_OTP_PURPOSE)
    sent = await send_email(
        email,
        "EduSpace – Password Reset Code",
        _otp_email_body(otp, user.get("full_name") or ""),
    )
    if not sent:
        domain = sending_domain()
        logger.warning(
            "Forgot-password OTP could not be delivered to %s (from=%s, domain=%s)",
            email,
            _from_address(),
            domain,
        )
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not send the reset code email. Please try again shortly.",
        )

    return StudentForgotSendOut(
        message="OTP sent to your linked Gmail. Check your inbox (and Spam/Junk).",
        masked_email=mask_email(email),
    )


def _require_gmail(user: dict | None, missing: str) -> tuple[dict, str]:
    if not user or not user.get("is_active", True):
        raise HTTPException(status.HTTP_404_NOT_FOUND, missing)
    email = (user.get("email") or "").strip().lower()
    if not is_gmail(email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail={"code": "NO_GMAIL_LINKED", "message": NO_GMAIL_MESSAGE},
        )
    return user, email


async def _reset_password(user: dict, email: str, new_password: str) -> dict:
    if not is_verified(email, purpose=_OTP_PURPOSE):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Please verify the OTP before setting a new password.",
        )
    client = get_client()
    await client.table("users").update({
        "password_hash": hash_password(new_password),
        "login_password": new_password,
        "must_change_password": False,
    }).eq("id", user["id"]).execute()
    clear(email, purpose=_OTP_PURPOSE)
    return {"message": "Password updated. You can sign in with your new password."}


# ── Student ───────────────────────────────────────────────────────────────────

@router.post("/student/send-otp", response_model=StudentForgotSendOut)
async def student_send_otp(body: StudentForgotSendIn) -> StudentForgotSendOut:
    user = await _find_student(body.school_id, body.admission_no)
    if not user or not user.get("is_active", True):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No student found with this admission number for your school.",
        )
    return await _send_forgot_otp(user)


@router.post("/student/verify-otp")
async def student_verify_otp(body: StudentForgotVerifyIn) -> dict:
    user, email = _require_gmail(
        await _find_student(body.school_id, body.admission_no),
        "Student not found.",
    )
    if not verify(email, body.otp, purpose=_OTP_PURPOSE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OTP. Please request a new one.")
    return {"verified": True, "masked_email": mask_email(email)}


@router.post("/student/reset-password")
async def student_reset_password(body: StudentForgotResetIn) -> dict:
    user, email = _require_gmail(
        await _find_student(body.school_id, body.admission_no),
        "Student not found.",
    )
    return await _reset_password(user, email, body.new_password)


# ── Teacher / Staff ───────────────────────────────────────────────────────────

@router.post("/staff/send-otp", response_model=StudentForgotSendOut)
async def staff_send_otp(body: StaffForgotSendIn) -> StudentForgotSendOut:
    user = await _find_staff(body.school_id, body.user_id)
    if not user or not user.get("is_active", True):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No staff account found with this User ID for your school.",
        )
    return await _send_forgot_otp(user)


@router.post("/staff/verify-otp")
async def staff_verify_otp(body: StaffForgotVerifyIn) -> dict:
    user, email = _require_gmail(
        await _find_staff(body.school_id, body.user_id),
        "Staff account not found.",
    )
    if not verify(email, body.otp, purpose=_OTP_PURPOSE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OTP. Please request a new one.")
    return {"verified": True, "masked_email": mask_email(email)}


@router.post("/staff/reset-password")
async def staff_reset_password(body: StaffForgotResetIn) -> dict:
    user, email = _require_gmail(
        await _find_staff(body.school_id, body.user_id),
        "Staff account not found.",
    )
    return await _reset_password(user, email, body.new_password)


# ── School Management (Admin) — OTP always to school Gmail ───────────────────

@router.post("/school/send-otp", response_model=StudentForgotSendOut)
async def school_send_otp(body: SchoolForgotSendIn) -> StudentForgotSendOut:
    # OTP always goes to the school Gmail (SCH***), not admin email.
    school_user = await _find_school_portal(body.school_id, "office_staff")
    if not school_user or not school_user.get("is_active", True):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No school account found for password reset.",
        )
    return await _send_forgot_otp(school_user)


@router.post("/school/verify-otp")
async def school_verify_otp(body: SchoolForgotVerifyIn) -> dict:
    _user, email = _require_gmail(
        await _find_school_portal(body.school_id, "office_staff"),
        "School account not found.",
    )
    if not verify(email, body.otp, purpose=_OTP_PURPOSE):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired OTP. Please request a new one.")
    return {"verified": True, "masked_email": mask_email(email)}


@router.post("/school/reset-password")
async def school_reset_password(body: SchoolForgotResetIn) -> dict:
    _user, email = _require_gmail(
        await _find_school_portal(body.school_id, "office_staff"),
        "School account not found.",
    )
    if not is_verified(email, purpose=_OTP_PURPOSE):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Please verify the OTP before setting a new password.",
        )
    await _sync_school_management_passwords(body.school_id, body.new_password)
    clear(email, purpose=_OTP_PURPOSE)
    return {"message": "Password updated. You can sign in with your new password."}
