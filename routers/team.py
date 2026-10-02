"""Team portal routes (TEAM01 institution code).

The TEAM01 institution code opens the internal Eduspace team portal instead of
a school sign-in. Team members authenticate with a shared access code plus
their own username/password, and can then send branded email to registered
schools (delivered through the eduspace@nextforms.in sender) or open the school
registration form.
"""
import base64
import logging
import re
import uuid
from pathlib import Path
from typing import Optional

import jwt
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr

from config import get_settings
from database import get_client
from services.chat_media_service import filename_from_media_url, resolve_chat_file
from services.email_service import send_email
from services.otp_service import clear, generate_and_store, verify
from utils.deps import require_roles
from utils.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/team", tags=["team"])
logger = logging.getLogger("eduspace.team")

_bearer = HTTPBearer(auto_error=False)

_TEAM_OTP_PURPOSE = "team_register"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
_EMAIL_RE = re.compile(r"^\S+@\S+\.\S+$")
_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

_MEMBER_COLUMNS = (
    "id,full_name,username,email,is_active,created_at,contributions,earnings,documents"
)


# ── Schemas ──────────────────────────────────────────────────────────────────


class AccessIn(BaseModel):
    access_code: str


class RegisterOtpIn(BaseModel):
    access_code: str
    email: EmailStr


class RegisterIn(BaseModel):
    access_code: str
    full_name: str
    username: str
    email: EmailStr
    otp: str
    password: str


class LoginIn(BaseModel):
    access_code: str
    username: str
    password: str


class MemberMetaIn(BaseModel):
    contributions: str = ""
    earnings: str = ""
    documents: str = ""


class PaymentIn(BaseModel):
    member_id: str
    amount: str
    note: str = ""


class PaymentUpdateIn(BaseModel):
    amount: str
    note: str = ""


class ContributionIn(BaseModel):
    member_id: str
    text: str


class ContributionUpdateIn(BaseModel):
    text: str


class VisitIn(BaseModel):
    school_name: str
    visit_date: str
    note: str = ""
    companions: str = ""


class VisitUpdateIn(BaseModel):
    school_name: str
    visit_date: str
    note: str = ""
    companions: str = ""


class EmailUpdateIn(BaseModel):
    email: EmailStr


class PasswordUpdateIn(BaseModel):
    current_password: str
    new_password: str


# ── Helpers ──────────────────────────────────────────────────────────────────


def _check_access_code(code: str) -> None:
    expected = (get_settings().team_access_code or "").strip()
    if not expected or (code or "").strip() != expected:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access code.")


def _member_public(member: dict) -> dict:
    return {
        "id": member["id"],
        "full_name": member["full_name"],
        "username": member["username"],
        "email": member["email"],
        "contributions": member.get("contributions") or "",
        "earnings": member.get("earnings") or "",
        "documents": member.get("documents") or "",
    }


def _team_token(member: dict) -> str:
    return create_access_token(
        user_id=member["id"],
        role="team_member",
        email=member["email"],
        school_id="",
    )


async def current_team_member(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    if not creds:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing authentication token")
    try:
        payload = decode_access_token(creds.credentials)
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")
    if payload.get("role") != "team_member" or not payload.get("sub"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a team session")
    client = get_client()
    res = (
        await client.table("team_members")
        .select(_MEMBER_COLUMNS)
        .eq("id", payload["sub"])
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Team member not found")
    member = res.data[0]
    if not member.get("is_active", True):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Team member is inactive")
    return member


TEAM_ADMIN_USERNAME = "abhaytripathi"


async def current_team_admin(
    member: dict = Depends(current_team_member),
) -> dict:
    """The team admin account manages everyone's earnings/contributions."""
    if (member.get("username") or "").lower() != TEAM_ADMIN_USERNAME:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin only")
    return member


def _split_emails(raw: str) -> list[str]:
    return [e.strip() for e in re.split(r"[,;\s]+", raw or "") if e.strip()]


def _team_otp_body(otp: str) -> str:
    return (
        f"Eduspace Team – Email Verification Code\n"
        f"{'=' * 42}\n\n"
        f"Your one-time verification code is:\n\n"
        f"    {otp}\n\n"
        f"This code expires in 10 minutes.\n\n"
        f"If you did not request this code, please ignore this email.\n\n"
        f"— The Eduspace Team\n"
    )


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/verify-access")
async def verify_access(body: AccessIn) -> dict:
    """Gate check for the shared team access code."""
    _check_access_code(body.access_code)
    return {"ok": True}


@router.post("/register/send-otp")
async def register_send_otp(body: RegisterOtpIn) -> dict:
    _check_access_code(body.access_code)
    email = body.email.lower()
    client = get_client()
    existing = (
        await client.table("team_members")
        .select("id")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists."
        )
    otp = generate_and_store(email, purpose=_TEAM_OTP_PURPOSE)
    sent = await send_email(
        email,
        "Eduspace Team – Email Verification Code",
        _team_otp_body(otp),
    )
    if not sent:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not send the verification email. Please try again shortly.",
        )
    return {"message": "OTP sent. Please check your inbox (and Spam/Junk folder)."}


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn) -> dict:
    _check_access_code(body.access_code)

    full_name = body.full_name.strip()
    username = body.username.strip()
    email = body.email.lower()

    if not full_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter your name.")
    if not _USERNAME_RE.match(username):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Username must be 3–30 characters (letters, numbers, . _ -).",
        )
    if len(body.password) < 6:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Password must be at least 6 characters."
        )
    if not verify(email, body.otp, purpose=_TEAM_OTP_PURPOSE):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Invalid or expired OTP. Please request a new one.",
        )

    client = get_client()
    dup_username = (
        await client.table("team_members")
        .select("id")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    if dup_username.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username is already taken.")

    res = (
        await client.table("team_members")
        .insert(
            {
                "full_name": full_name,
                "username": username,
                "email": email,
                "password_hash": hash_password(body.password),
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create the account."
        )
    clear(email, purpose=_TEAM_OTP_PURPOSE)
    member = res.data[0]
    logger.info("Team member registered: %s <%s>", member["username"], email)
    return {"access_token": _team_token(member), "member": _member_public(member)}


@router.post("/login")
async def login(body: LoginIn) -> dict:
    _check_access_code(body.access_code)
    username = body.username.strip()
    if not username or not body.password:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter your username and password."
        )
    client = get_client()
    res = (
        await client.table("team_members")
        .select(_MEMBER_COLUMNS + ",password_hash")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    member = res.data[0] if res.data else None
    if not member or not verify_password(body.password, member.get("password_hash", "")):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Invalid username or password."
        )
    if not member.get("is_active", True):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This account is inactive.")
    return {"access_token": _team_token(member), "member": _member_public(member)}


@router.get("/me")
async def me(member: dict = Depends(current_team_member)) -> dict:
    return {"member": _member_public(member)}


@router.get("/directory")
async def directory(member: dict = Depends(current_team_member)) -> dict:
    """Team roster — names shown on the dashboard's members list."""
    client = get_client()
    res = (
        await client.table("team_members")
        .select("id,full_name,username")
        .eq("is_active", True)
        .order("full_name")
        .execute()
    )
    return {
        "members": [
            {"id": m["id"], "full_name": m["full_name"], "username": m["username"]}
            for m in (res.data or [])
        ]
    }


@router.get("/schools")
async def list_schools(member: dict = Depends(current_team_member)) -> dict:
    """Schools the team member can email (name + registered email)."""
    client = get_client()
    res = (
        await client.table("schools")
        .select("id,school_name,email,institution_code,city")
        .eq("is_active", True)
        .order("school_name")
        .execute()
    )
    schools = [
        {
            "id": s["id"],
            "name": s.get("school_name") or "",
            "email": s.get("email") or "",
            "institution_code": s.get("institution_code") or "",
            "city": s.get("city") or "",
        }
        for s in (res.data or [])
    ]
    return {"schools": schools}


@router.post("/send-email")
async def send_team_email(
    to: str = Form(...),
    subject: str = Form(...),
    description: str = Form(...),
    school: str = Form(""),
    cc: str = Form(""),
    bcc: str = Form(""),
    file: Optional[UploadFile] = File(None),
    member: dict = Depends(current_team_member),
) -> dict:
    """Send a branded email to a school through the eduspace@nextforms.in sender."""
    to_addr = to.strip()
    if not _EMAIL_RE.match(to_addr):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter a valid recipient email."
        )
    if not subject.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a subject.")
    if not description.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a description.")

    cc_list = _split_emails(cc)
    bcc_list = _split_emails(bcc)
    for addr in cc_list + bcc_list:
        if not _EMAIL_RE.match(addr):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"Invalid email address: {addr}"
            )

    attachments: list[dict] = []
    if file is not None and file.filename:
        content = await file.read()
        if len(content) > _MAX_ATTACHMENT_BYTES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "Attachment must be 10 MB or smaller."
            )
        attachments.append(
            {
                "filename": file.filename,
                "content": base64.b64encode(content).decode(),
            }
        )

    school_line = f"School: {school.strip()}\n\n" if school.strip() else ""
    body_text = (
        f"{school_line}"
        f"{description.strip()}\n\n"
        f"— {member['full_name']} (Eduspace Team)\n"
    )

    sent = await send_email(
        to_addr,
        subject.strip(),
        body_text,
        reply_to=member["email"],
        cc=cc_list or None,
        bcc=bcc_list or None,
        attachments=attachments or None,
    )
    if not sent:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Could not send the email. Please try again shortly.",
        )
    logger.info(
        "Team email sent by %s to %s (cc=%d bcc=%d attachments=%d)",
        member["username"],
        to_addr,
        len(cc_list),
        len(bcc_list),
        len(attachments),
    )
    try:
        client = get_client()
        await client.table("team_emails").insert(
            {
                "member_id": member["id"],
                "school_name": school.strip(),
                "to_email": to_addr,
                "subject": subject.strip(),
                "cc": cc.strip(),
                "bcc": bcc.strip(),
                "description": description.strip(),
                "attachment": file.filename if file is not None and file.filename else "",
            }
        ).execute()
    except Exception:
        logger.warning("Could not log team email for member %s", member["id"])
    return {"message": "Email sent."}


@router.get("/sent-emails")
async def sent_emails(member: dict = Depends(current_team_member)) -> dict:
    """Emails this member has sent through the portal, newest first."""
    client = get_client()
    res = (
        await client.table("team_emails")
        .select("id,school_name,to_email,subject,cc,bcc,description,attachment,created_at")
        .eq("member_id", member["id"])
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return {"emails": res.data or []}


@router.get("/emails/all")
async def all_emails(member: dict = Depends(current_team_member)) -> dict:
    """Every team member's emails — feeds the team-wide stats."""
    client = get_client()
    res = (
        await client.table("team_emails")
        .select("id,member_id,school_name,to_email,subject,created_at")
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    return {"emails": res.data or []}


# ── Admin (abhaytripathi) — manage everyone's contributions & earnings ───────


@router.get("/admin/members")
async def admin_members(admin: dict = Depends(current_team_admin)) -> dict:
    """All members with their meta fields, for the admin editors."""
    client = get_client()
    res = (
        await client.table("team_members")
        .select(_MEMBER_COLUMNS)
        .order("created_at")
        .execute()
    )
    return {"members": res.data or []}


@router.put("/admin/members/{member_id}")
async def admin_update_member(
    member_id: str,
    body: MemberMetaIn,
    admin: dict = Depends(current_team_admin),
) -> dict:
    """Set a member's contributions / earnings / documents."""
    client = get_client()
    res = (
        await client.table("team_members")
        .update(
            {
                "contributions": body.contributions or "",
                "earnings": body.earnings or "",
                "documents": body.documents or "",
            }
        )
        .eq("id", member_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return {"member": res.data[0]}


async def _sync_member_earnings(member_id: str) -> None:
    """Roll up a member's payment ledger into the flat `earnings` field."""
    client = get_client()
    res = (
        await client.table("team_payments")
        .select("amount")
        .eq("member_id", member_id)
        .execute()
    )
    total = 0.0
    for row in res.data or []:
        digits = re.sub(r"[^\d.]", "", str(row.get("amount") or ""))
        if digits:
            try:
                total += float(digits)
            except ValueError:
                pass
    earnings = f"₹{total:,.2f}".rstrip("0").rstrip(".") if total > 0 else ""
    await (
        client.table("team_members")
        .update({"earnings": earnings})
        .eq("id", member_id)
        .execute()
    )


async def _sync_member_contributions(member_id: str) -> None:
    """Roll up a member's contribution log into the flat `contributions` field."""
    client = get_client()
    res = (
        await client.table("team_contributions")
        .select("text")
        .eq("member_id", member_id)
        .order("created_at")
        .execute()
    )
    lines = [
        f"• {row['text'].strip()}"
        for row in (res.data or [])
        if row.get("text", "").strip()
    ]
    await (
        client.table("team_members")
        .update({"contributions": "\n".join(lines)})
        .eq("id", member_id)
        .execute()
    )


async def _member_or_404(member_id: str) -> dict:
    client = get_client()
    res = (
        await client.table("team_members")
        .select("id,full_name")
        .eq("id", member_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return res.data[0]


# Payments (track record of what was paid and when)
@router.post("/admin/payments")
async def add_payment(
    body: PaymentIn, admin: dict = Depends(current_team_admin)
) -> dict:
    member = await _member_or_404(body.member_id)
    client = get_client()
    res = (
        await client.table("team_payments")
        .insert(
            {
                "member_id": member["id"],
                "member_name": member["full_name"],
                "amount": body.amount.strip(),
                "note": (body.note or "").strip(),
            }
        )
        .execute()
    )
    await _sync_member_earnings(member["id"])
    return {"payment": res.data[0]}


@router.get("/admin/payments")
async def list_payments(
    member_id: Optional[str] = None,
    admin: dict = Depends(current_team_admin),
) -> dict:
    client = get_client()
    q = (
        client.table("team_payments")
        .select("id,member_id,member_name,amount,note,created_at")
        .order("created_at", desc=True)
        .limit(300)
    )
    if member_id:
        q = q.eq("member_id", member_id)
    res = await q.execute()
    return {"payments": res.data or []}


@router.put("/admin/payments/{payment_id}")
async def update_payment(
    payment_id: str,
    body: PaymentUpdateIn,
    admin: dict = Depends(current_team_admin),
) -> dict:
    client = get_client()
    res = (
        await client.table("team_payments")
        .update(
            {"amount": body.amount.strip(), "note": (body.note or "").strip()}
        )
        .eq("id", payment_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    await _sync_member_earnings(res.data[0]["member_id"])
    return {"payment": res.data[0]}


@router.delete("/admin/payments/{payment_id}")
async def delete_payment(
    payment_id: str, admin: dict = Depends(current_team_admin)
) -> dict:
    client = get_client()
    res = (
        await client.table("team_payments")
        .delete()
        .eq("id", payment_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    await _sync_member_earnings(res.data[0]["member_id"])
    return {"ok": True}


# Contribution entries
@router.post("/admin/contributions")
async def add_contribution(
    body: ContributionIn, admin: dict = Depends(current_team_admin)
) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contribution is empty")
    member = await _member_or_404(body.member_id)
    client = get_client()
    res = (
        await client.table("team_contributions")
        .insert(
            {
                "member_id": member["id"],
                "member_name": member["full_name"],
                "text": text,
            }
        )
        .execute()
    )
    await _sync_member_contributions(member["id"])
    return {"contribution": res.data[0]}


@router.get("/admin/contributions")
async def list_contributions(
    member_id: Optional[str] = None,
    admin: dict = Depends(current_team_admin),
) -> dict:
    client = get_client()
    q = (
        client.table("team_contributions")
        .select("id,member_id,member_name,text,created_at")
        .order("created_at", desc=True)
        .limit(300)
    )
    if member_id:
        q = q.eq("member_id", member_id)
    res = await q.execute()
    return {"contributions": res.data or []}


@router.put("/admin/contributions/{contribution_id}")
async def update_contribution(
    contribution_id: str,
    body: ContributionUpdateIn,
    admin: dict = Depends(current_team_admin),
) -> dict:
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contribution is empty")
    client = get_client()
    res = (
        await client.table("team_contributions")
        .update({"text": text})
        .eq("id", contribution_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    await _sync_member_contributions(res.data[0]["member_id"])
    return {"contribution": res.data[0]}


@router.delete("/admin/contributions/{contribution_id}")
async def delete_contribution(
    contribution_id: str, admin: dict = Depends(current_team_admin)
) -> dict:
    client = get_client()
    res = (
        await client.table("team_contributions")
        .delete()
        .eq("id", contribution_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Contribution not found")
    await _sync_member_contributions(res.data[0]["member_id"])
    return {"ok": True}


@router.delete("/admin/members/{member_id}")
async def admin_delete_member(
    member_id: str, admin: dict = Depends(current_team_admin)
) -> dict:
    """Remove a team member and their records. Admin can't delete themself."""
    if member_id == admin["id"]:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "You can't delete your own account"
        )
    client = get_client()
    for table in (
        "team_payments",
        "team_contributions",
        "team_visits",
        "team_emails",
    ):
        await client.table(table).delete().eq("member_id", member_id).execute()
    res = (
        await client.table("team_members")
        .delete()
        .eq("id", member_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Member not found")
    return {"ok": True}


# ── Admin — school stats + payment overview (same data as the developer console) ─

_STAFF_STAT_ROLES = {
    "receptionist", "accountant", "librarian", "transport_manager",
    "hostel_warden", "hostel_manager", "school_doctor",
    "school_admin",
}


@router.get("/admin/school-stats")
async def admin_school_stats(admin: dict = Depends(current_team_admin)) -> dict:
    """Every registered school with student/teacher/staff counts."""
    client = get_client()
    schools_res = (
        await client.table("schools")
        .select(
            "id,school_name,institution_code,is_active,is_trial,city,state,subscription_plan"
        )
        .order("school_name")
        .limit(1000)
        .execute()
    )
    schools = schools_res.data or []
    if not schools:
        return {"schools": []}

    school_ids = [s["id"] for s in schools]
    users_res = (
        await client.table("users")
        .select("school_id,role,is_active")
        .in_("school_id", school_ids)
        .execute()
    )
    counts: dict[str, dict[str, int]] = {}
    for row in users_res.data or []:
        sid = row.get("school_id")
        if not sid:
            continue
        if sid not in counts:
            counts[sid] = {"student": 0, "teacher": 0, "staff": 0}
        if not row.get("is_active", True):
            continue
        role = row.get("role") or ""
        if role == "student":
            counts[sid]["student"] += 1
        elif role == "teacher":
            counts[sid]["teacher"] += 1
        elif role in _STAFF_STAT_ROLES:
            counts[sid]["staff"] += 1

    out = []
    for s in schools:
        c = counts.get(s["id"], {"student": 0, "teacher": 0, "staff": 0})
        out.append(
            {
                "id": s["id"],
                "school_name": s.get("school_name") or "",
                "institution_code": s.get("institution_code") or "",
                "is_active": s.get("is_active", True),
                "is_trial": s.get("is_trial", False),
                "city": s.get("city"),
                "state": s.get("state"),
                "subscription_plan": s.get("subscription_plan") or "free",
                "student_count": c["student"],
                "teacher_count": c["teacher"],
                "staff_count": c["staff"],
            }
        )
    return {"schools": out}


@router.get("/admin/payment-overview")
async def admin_payment_overview(admin: dict = Depends(current_team_admin)) -> dict:
    """School payment/subscription overview — same as the developer console."""
    client = get_client()
    schools_res = (
        await client.table("schools")
        .select(
            "id,school_name,institution_code,is_active,is_trial,subscription_plan,city,state"
        )
        .order("school_name")
        .limit(1000)
        .execute()
    )
    schools = schools_res.data or []
    if not schools:
        return {"schools": [], "total_revenue": 0, "total_paid": 0, "total_pending": 0}

    school_ids = [s["id"] for s in schools]
    payments_res = (
        await client.table("fee_payments")
        .select("school_id,payment_status,total")
        .in_("school_id", school_ids)
        .execute()
    )
    pay_stats: dict[str, dict] = {}
    for row in payments_res.data or []:
        sid = row.get("school_id")
        if not sid:
            continue
        if sid not in pay_stats:
            pay_stats[sid] = {"revenue": 0, "paid_count": 0, "pending_count": 0}
        ps = (row.get("payment_status") or "").lower()
        total = float(row.get("total") or 0)
        if ps == "paid":
            pay_stats[sid]["revenue"] += total
            pay_stats[sid]["paid_count"] += 1
        elif ps in ("created", "pending"):
            pay_stats[sid]["pending_count"] += 1

    schools_out = []
    total_revenue = 0.0
    total_paid = 0
    total_pending = 0
    for s in schools:
        sid = s["id"]
        ps = pay_stats.get(sid, {"revenue": 0, "paid_count": 0, "pending_count": 0})
        revenue = round(ps["revenue"], 2)
        total_revenue += revenue
        total_paid += ps["paid_count"]
        total_pending += ps["pending_count"]
        schools_out.append(
            {
                "id": sid,
                "school_name": s.get("school_name") or "",
                "institution_code": s.get("institution_code") or "",
                "is_active": s.get("is_active", True),
                "is_trial": s.get("is_trial", False),
                "subscription_plan": s.get("subscription_plan") or "free",
                "city": s.get("city"),
                "state": s.get("state"),
                "revenue": revenue,
                "paid_count": ps["paid_count"],
                "pending_count": ps["pending_count"],
            }
        )

    return {
        "schools": schools_out,
        "total_revenue": round(total_revenue, 2),
        "total_paid": total_paid,
        "total_pending": total_pending,
    }


_SUB_COLS = (
    "id,school_name,institution_code,city,state,is_active,is_trial,"
    "subscription_plan,display_plan,actual_plan,subscription_amount,payment_link,access_blocked,"
    "billing_cycle,subscription_start_date,subscription_end_date,plan_cancelled"
)


def _sub_row(s: dict) -> dict:
    return {
        "id": s["id"],
        "school_name": s.get("school_name") or "",
        "institution_code": s.get("institution_code") or "",
        "city": s.get("city"),
        "state": s.get("state"),
        "is_active": s.get("is_active", True),
        "is_trial": s.get("is_trial", False),
        "subscription_plan": s.get("subscription_plan") or "free",
        "display_plan": s.get("display_plan") or s.get("subscription_plan") or "free",
        "actual_plan": s.get("actual_plan") or s.get("subscription_plan") or "free",
        "subscription_amount": float(s.get("subscription_amount") or 0),
        "payment_link": s.get("payment_link") or "",
        "access_blocked": bool(s.get("access_blocked")),
        "billing_cycle": s.get("billing_cycle") or "monthly",
        "subscription_start_date": s.get("subscription_start_date"),
        "subscription_end_date": s.get("subscription_end_date"),
        "plan_cancelled": bool(s.get("plan_cancelled")),
    }


@router.get("/admin/subscriptions")
async def admin_subscriptions(admin: dict = Depends(current_team_admin)) -> dict:
    """All schools with subscription management fields (dev-console parity)."""
    client = get_client()
    res = (
        await client.table("schools")
        .select(_SUB_COLS)
        .order("school_name")
        .limit(1000)
        .execute()
    )
    return {"schools": [_sub_row(s) for s in res.data or []]}


_SUB_EDITABLE = {
    "display_plan", "actual_plan", "subscription_amount",
    "payment_link", "access_blocked", "billing_cycle",
    "subscription_start_date", "subscription_end_date",
}


@router.patch("/admin/subscriptions/{school_id}")
async def admin_update_subscription(
    school_id: str,
    body: dict,
    admin: dict = Depends(current_team_admin),
) -> dict:
    """Update subscription fields for a school (dev-console parity)."""
    updates = {k: v for k, v in body.items() if k in _SUB_EDITABLE}
    if not updates:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No valid fields to update")
    client = get_client()
    res = (
        await client.table("schools")
        .update(updates)
        .eq("id", school_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return {"ok": True, **updates}


@router.post("/admin/subscriptions/{school_id}/payment-done")
async def admin_payment_done(
    school_id: str, admin: dict = Depends(current_team_admin)
) -> dict:
    """Mark payment done — clears the payment link and unblocks access."""
    client = get_client()
    res = (
        await client.table("schools")
        .update({"payment_link": None, "access_blocked": False})
        .eq("id", school_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return {"ok": True, "payment_link": None, "access_blocked": False}


@router.post("/admin/subscriptions/{school_id}/cancel-plan")
async def admin_cancel_plan(
    school_id: str, admin: dict = Depends(current_team_admin)
) -> dict:
    """Cancel a school's plan — blocks non-admin login."""
    client = get_client()
    res = (
        await client.table("schools")
        .update(
            {
                "plan_cancelled": True,
                "access_blocked": True,
                "display_plan": None,
                "actual_plan": None,
                "subscription_plan": None,
            }
        )
        .eq("id", school_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return {"ok": True, "plan_cancelled": True}


@router.get("/admin/force-update")
async def admin_get_force_update(admin: dict = Depends(current_team_admin)) -> dict:
    """Read the global force-update flag (dev-console parity)."""
    client = get_client()
    res = (
        await client.table("app_force_update")
        .select("force_update,message,updated_at")
        .eq("id", 1)
        .limit(1)
        .execute()
    )
    row = (res.data or [{}])[0]
    return {
        "force_update": bool(row.get("force_update")),
        "message": row.get("message"),
        "updated_at": row.get("updated_at"),
    }


@router.post("/admin/force-update")
async def admin_set_force_update(
    body: dict, admin: dict = Depends(current_team_admin)
) -> dict:
    """Toggle the global force-update notification."""
    client = get_client()
    force_update = bool(body.get("force_update", False))
    message = (body.get("message") or "").strip() or None
    await client.table("app_force_update").upsert(
        {
            "id": 1,
            "force_update": force_update,
            "message": message,
            "updated_at": "now()",
        }
    ).execute()
    return {"force_update": force_update, "message": message}


@router.get("/admin/join-requests")
async def admin_join_requests(admin: dict = Depends(current_team_admin)) -> dict:
    """School 'apply for free trial' requests submitted on the landing page."""
    client = get_client()
    res = (
        await client.table("school_join_requests")
        .select("id,school_name,email,contact,address,created_at")
        .order("created_at", desc=True)
        .limit(300)
        .execute()
    )
    return {"requests": res.data or []}


# ── Admin — help inbox (same data as the developer help inbox) ───────────────

_HELP_COLUMNS = "id,user_id,sender,sender_label,message,media_url,media_type,media_name,created_at"


class HelpReplyIn(BaseModel):
    message: str


@router.get("/admin/help-conversations")
async def admin_help_conversations(admin: dict = Depends(current_team_admin)) -> dict:
    """All user help conversations grouped by user — dev inbox parity."""
    client = get_client()
    res = (
        await client.table("help_messages")
        .select(_HELP_COLUMNS)
        .order("created_at", desc=False)
        .limit(5000)
        .execute()
    )
    convos: dict[str, dict] = {}
    for r in res.data or []:
        uid = r["user_id"]
        if uid not in convos:
            convos[uid] = {
                "userId": uid,
                "senderLabel": r["sender_label"],
                "lastMessage": r["message"],
                "lastAt": r["created_at"],
                "messages": [],
            }
        convos[uid]["messages"].append(
            {
                "id": r["id"],
                "sender": r["sender"],
                "message": r["message"],
                "mediaUrl": (
                    f"/api/team/admin/help-files/{uid}/{filename_from_media_url(r['media_url'])}"
                    if r.get("media_url")
                    else None
                ),
                "mediaType": r.get("media_type"),
                "mediaName": r.get("media_name"),
                "createdAt": r["created_at"],
            }
        )
        convos[uid]["lastMessage"] = r["message"] or (
            "Image" if r.get("media_type") == "image" else "Attachment"
        )
        convos[uid]["lastAt"] = r["created_at"]

    sorted_convos = sorted(convos.values(), key=lambda c: c["lastAt"], reverse=True)
    return {"conversations": sorted_convos}


@router.post("/admin/help-conversations/{user_id}/reply")
async def admin_help_reply(
    user_id: str,
    body: HelpReplyIn,
    admin: dict = Depends(current_team_admin),
) -> dict:
    """Reply to a user's help conversation as the team/developer."""
    message = body.message.strip()
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Message is empty")
    client = get_client()
    existing = (
        await client.table("help_messages")
        .select("sender_label")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    res = (
        await client.table("help_messages")
        .insert(
            {
                "user_id": user_id,
                "sender": "developer",
                "sender_label": existing.data[0]["sender_label"],
                "message": message,
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not send reply")
    return {"ok": True, "message": res.data[0]}


@router.get("/admin/help-files/{owner_id}/{filename}")
async def admin_help_file(
    owner_id: str,
    filename: str,
    admin: dict = Depends(current_team_admin),
) -> FileResponse:
    """Team admin: serve a help-chat attachment uploaded by a user."""
    path, mime = resolve_chat_file(f"help/{owner_id}", filename)
    return FileResponse(path, media_type=mime, filename=filename)


# ── Shared documents — admin uploads files, members view/download ────────────

_DOCS_DIR = Path(__file__).resolve().parent.parent / "uploads" / "team"
_DOCS_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/admin/documents")
async def upload_document(
    file: UploadFile = File(...),
    admin: dict = Depends(current_team_admin),
) -> dict:
    """Store a shared team document."""
    original = Path(file.filename or "document").name
    stored = f"{uuid.uuid4().hex}_{original}"
    dest = _DOCS_DIR / stored
    data = await file.read()
    dest.write_bytes(data)
    client = get_client()
    res = (
        await client.table("team_documents")
        .insert(
            {
                "file_name": original,
                "stored_name": stored,
                "size_bytes": len(data),
                "uploaded_by": admin["full_name"],
            }
        )
        .execute()
    )
    return {"document": res.data[0]}


@router.get("/documents")
async def list_documents(member: dict = Depends(current_team_member)) -> dict:
    client = get_client()
    res = (
        await client.table("team_documents")
        .select("id,file_name,size_bytes,uploaded_by,created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return {"documents": res.data or []}


@router.get("/documents/{doc_id}/download")
async def download_document(
    doc_id: str, member: dict = Depends(current_team_member)
):
    from fastapi.responses import FileResponse

    client = get_client()
    res = (
        await client.table("team_documents")
        .select("file_name,stored_name")
        .eq("id", doc_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    path = _DOCS_DIR / res.data[0]["stored_name"]
    if not path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on server")
    return FileResponse(path, filename=res.data[0]["file_name"])


@router.delete("/admin/documents/{doc_id}")
async def delete_document(
    doc_id: str, admin: dict = Depends(current_team_admin)
) -> dict:
    client = get_client()
    res = (
        await client.table("team_documents")
        .delete()
        .eq("id", doc_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    try:
        (_DOCS_DIR / res.data[0]["stored_name"]).unlink(missing_ok=True)
    except OSError:
        pass
    return {"ok": True}


# ── Member settings (edit email / change password) ───────────────────────────


@router.put("/me/email")
async def update_email(
    body: EmailUpdateIn, member: dict = Depends(current_team_member)
) -> dict:
    email = body.email.lower()
    client = get_client()
    dup = (
        await client.table("team_members")
        .select("id")
        .eq("email", email)
        .neq("id", member["id"])
        .limit(1)
        .execute()
    )
    if dup.data:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "An account with this email already exists."
        )
    res = (
        await client.table("team_members")
        .update({"email": email})
        .eq("id", member["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found")
    logger.info("Team member %s changed email to %s", member["username"], email)
    return {"member": _member_public(res.data[0])}


@router.put("/me/password")
async def update_password(
    body: PasswordUpdateIn, member: dict = Depends(current_team_member)
) -> dict:
    if len(body.new_password) < 6:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Password must be at least 6 characters."
        )
    client = get_client()
    res = (
        await client.table("team_members")
        .select("password_hash")
        .eq("id", member["id"])
        .limit(1)
        .execute()
    )
    row = res.data[0] if res.data else None
    if not row or not verify_password(
        body.current_password, row.get("password_hash", "")
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "Current password is incorrect."
        )
    await (
        client.table("team_members")
        .update({"password_hash": hash_password(body.new_password)})
        .eq("id", member["id"])
        .execute()
    )
    logger.info("Team member %s changed password", member["username"])
    return {"ok": True}


# ── School visits ────────────────────────────────────────────────────────────


@router.post("/visits", status_code=status.HTTP_201_CREATED)
async def create_visit(
    body: VisitIn, member: dict = Depends(current_team_member)
) -> dict:
    """Log a planned school visit."""
    school_name = body.school_name.strip()
    visit_date = body.visit_date.strip()
    if not school_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick a school.")
    if not visit_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter when you're visiting."
        )
    client = get_client()
    res = (
        await client.table("team_visits")
        .insert(
            {
                "member_id": member["id"],
                "member_name": member["full_name"],
                "school_name": school_name,
                "visit_date": visit_date,
                "note": (body.note or "").strip(),
                "companions": (body.companions or "").strip(),
            }
        )
        .execute()
    )
    if not res.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not save the visit."
        )
    return {"visit": res.data[0]}


@router.get("/visits")
async def list_visits(member: dict = Depends(current_team_member)) -> dict:
    """Everyone's planned visits — scheduled first, newest first."""
    client = get_client()
    res = (
        await client.table("team_visits")
        .select(
            "id,member_id,member_name,school_name,visit_date,note,companions,done,created_at"
        )
        .order("done")
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    return {"visits": res.data or []}


@router.put("/visits/{visit_id}/done")
async def mark_visit_done(
    visit_id: str, member: dict = Depends(current_team_member)
) -> dict:
    """Mark your own visit as done."""
    client = get_client()
    res = (
        await client.table("team_visits")
        .update({"done": True})
        .eq("id", visit_id)
        .eq("member_id", member["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    return {"ok": True}


@router.put("/visits/{visit_id}")
async def update_visit(
    visit_id: str,
    body: VisitUpdateIn,
    member: dict = Depends(current_team_member),
) -> dict:
    """Edit your own visit — school, date, note, companions."""
    school_name = body.school_name.strip()
    visit_date = body.visit_date.strip()
    if not school_name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick a school.")
    if not visit_date:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Enter when you're visiting."
        )
    client = get_client()
    res = (
        await client.table("team_visits")
        .update(
            {
                "school_name": school_name,
                "visit_date": visit_date,
                "note": (body.note or "").strip(),
                "companions": (body.companions or "").strip(),
            }
        )
        .eq("id", visit_id)
        .eq("member_id", member["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    return {"visit": res.data[0]}


@router.delete("/visits/{visit_id}")
async def delete_visit(
    visit_id: str, member: dict = Depends(current_team_member)
) -> dict:
    """Delete your own visit."""
    client = get_client()
    res = (
        await client.table("team_visits")
        .delete()
        .eq("id", visit_id)
        .eq("member_id", member["id"])
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Visit not found")
    return {"ok": True}


# ── Developer endpoints (set per-member contributions/earnings/documents) ────


@router.get("/members")
async def list_members(
    user: dict = Depends(require_roles("developer")),
) -> dict:
    """All team members — for the developer account to manage."""
    client = get_client()
    res = (
        await client.table("team_members")
        .select(_MEMBER_COLUMNS)
        .order("full_name")
        .execute()
    )
    return {"members": [_member_public(m) for m in (res.data or [])]}


@router.put("/members/{member_id}")
async def update_member_meta(
    member_id: str,
    body: MemberMetaIn,
    user: dict = Depends(require_roles("developer")),
) -> dict:
    """Developer sets a member's contributions and earnings text."""
    client = get_client()
    res = (
        await client.table("team_members")
        .update(
            {
                "contributions": (body.contributions or "").strip(),
                "earnings": (body.earnings or "").strip(),
                "documents": (body.documents or "").strip(),
            }
        )
        .eq("id", member_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Team member not found")
    logger.info("Developer %s updated team member %s meta", user.get("id"), member_id)
    return {"member": _member_public(res.data[0])}
