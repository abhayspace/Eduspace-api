"""Transactional email delivery via Resend.

If RESEND_API_KEY is not configured, the message is logged instead of sent
so that flows such as school registration still succeed in development.

All emails are sent from RESEND_FROM_EMAIL (defaults to
EduSpace <eduspace@nextforms.in>).
"""
import asyncio
import logging
import re
from html import escape

import resend

from config import get_settings

logger = logging.getLogger("eduspace.email")

DEFAULT_FROM = "EduSpace <eduspace@nextforms.in>"


def _from_address() -> str:
    settings = get_settings()
    value = (settings.mail_from_address or "").strip()
    return value or DEFAULT_FROM


def sending_domain() -> str:
    """Extract the bare domain from the configured From address."""
    from_addr = _from_address()
    match = re.search(r"<([^>]+)>", from_addr)
    email = (match.group(1) if match else from_addr).strip()
    if "@" in email:
        return email.split("@", 1)[1].lower()
    return email.lower() or "nextforms.in"


def _send_sync(
    to_address: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    settings = get_settings()
    api_key = (settings.resend_api_key or "").strip()
    if not api_key:
        logger.warning(
            "Email not configured (RESEND_API_KEY missing). "
            "Would have sent to %s | subject=%r | from=%r",
            to_address,
            subject,
            _from_address(),
        )
        logger.info("Email body (dev fallback):\n%s", body_text)
        return False

    resend.api_key = api_key

    params: dict = {
        "from": _from_address(),
        "to": [to_address],
        "subject": subject,
        "text": body_text,
        # Resend requires html or text; provide a simple HTML fallback from plain text.
        "html": body_html
        or f"<pre style=\"font-family:inherit;white-space:pre-wrap\">{escape(body_text)}</pre>",
    }
    if reply_to:
        params["reply_to"] = reply_to

    try:
        result = resend.Emails.send(params)
        email_id = result.get("id") if isinstance(result, dict) else getattr(result, "id", None)
        logger.info(
            "Sent email via Resend to %s | subject=%r | id=%s",
            to_address,
            subject,
            email_id,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        # ResendError often includes a useful message (e.g. domain not verified).
        detail = getattr(exc, "message", None) or str(exc)
        code = getattr(exc, "code", None) or getattr(exc, "error_type", None)
        logger.error(
            "Failed to send email to %s from %s | code=%s | error=%s",
            to_address,
            params.get("from"),
            code,
            detail,
        )
        return False


async def send_email(
    to_address: str,
    subject: str,
    body_text: str,
    body_html: str | None = None,
    reply_to: str | None = None,
) -> bool:
    """Send an email without blocking the event loop."""
    return await asyncio.to_thread(_send_sync, to_address, subject, body_text, body_html, reply_to)


async def send_support_query_email(
    *,
    to_address: str,
    reply_to: str,
    issue_label: str,
    user_email: str,
    message: str,
    title: str = "",
    school_name: str = "",
    institution_code: str = "",
) -> bool:
    school_line = ""
    if school_name or institution_code:
        school_line = f"\nSchool            : {school_name or '—'}"
        if institution_code:
            school_line += f"\nInstitution Code  : {institution_code}"

    title_line = f"\nTitle             : {title}" if title else ""

    body = f"""
EduSpace Support Query
======================

Issue Type        : {issue_label}{title_line}
User Email        : {user_email}{school_line}

Message
-------
{message}

---
Reply directly to this email to respond to the user ({user_email}).
""".strip()

    subject = f"EduSpace Support — {title or issue_label}"
    return await send_email(to_address, subject, body, reply_to=reply_to)


def build_school_welcome_email(
    *,
    school_name: str,
    institution_code: str,
    school_email: str,
    temp_password: str,
    city: str = "",
    state: str = "",
    board: str = "",
    school_type: str = "",
) -> str:
    location = ", ".join(p for p in (city, state) if p)
    details = " | ".join(p for p in (board, school_type) if p)
    plain = f"""
Welcome to EduSpace – Your School Management Login Credentials
==============================================================

Dear {school_name} Team,

Congratulations! Your school has been successfully registered on EduSpace.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCHOOL DETAILS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
School Name       : {school_name}
Location          : {location or "—"}
Type / Board      : {details or "—"}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SCHOOL MANAGEMENT LOGIN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Institution Code  : {institution_code}
School Email      : {school_email}
Temporary Password: {temp_password}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO SIGN IN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Open the EduSpace app.
2. Enter your Institution Code: {institution_code}
3. Open School Management.
4. Enter your Temporary Password (shown above).
5. You will be prompted to change your password on first login.

⚠️  IMPORTANT: Use this school password for School Management (Admin) login.
    Password reset codes are sent only to this school Gmail.
    Please change your password immediately after first login.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
NEXT STEPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
• Add your teachers and students from the dashboard.
• Configure classes, subjects, and timetables.
• Enable attendance, homework, and fee management modules.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HELP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Need help? Use the Help Center inside the EduSpace app.

Thank you for choosing EduSpace – empowering modern schools.

— The EduSpace Team
""".strip()
    return plain


def build_admin_welcome_email(
    *,
    school_name: str,
    admin_name: str,
    institution_code: str,
    admin_email: str,
    temp_password: str,
) -> str:
    """Deprecated: welcome credentials are sent only to the school email."""
    plain = f"""
Welcome to EduSpace – School Management Login
=============================================

Dear {admin_name},

Your school {school_name} is registered on EduSpace.
Login credentials are sent to the school Gmail only.
Use School Management with the school password.

Institution Code: {institution_code}
""".strip()
    return plain
