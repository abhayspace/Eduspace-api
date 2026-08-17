"""Business logic for free trial school registration and lifecycle."""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException

from database import get_client
from schemas.school import TrialRegisterIn
from services.email_service import (
    build_trial_welcome_email,
    build_trial_expired_email,
    send_email,
)
from services.otp_service import is_verified
from utils.codes import (
    generate_school_login_user_code,
    generate_temp_password,
    generate_unique_code_variants,
)
from utils.security import hash_password

logger = logging.getLogger("eduspace.trial")

TRIAL_DAYS = 7


async def _next_institution_code(school_name: str) -> str:
    client = get_client()
    for candidate in generate_unique_code_variants(school_name):
        res = (
            await client.table("schools")
            .select("id")
            .eq("institution_code", candidate)
            .limit(1)
            .execute()
        )
        if not res.data:
            return candidate
    raise HTTPException(status_code=500, detail="Could not allocate an institution code")


async def _next_school_login_user_code() -> str:
    client = get_client()
    res = (
        await client.table("users")
        .select("user_code")
        .like("user_code", "SCH%")
        .execute()
    )
    codes = [r["user_code"] for r in (res.data or []) if r.get("user_code")]
    nums = []
    for c in codes:
        try:
            nums.append(int(c[3:]))
        except (ValueError, IndexError):
            pass
    current_max = max(nums) if nums else 0
    return generate_school_login_user_code(current_max)


async def _email_taken(email: str) -> bool:
    client = get_client()
    res = (
        await client.table("users")
        .select("id")
        .eq("email", email)
        .limit(1)
        .execute()
    )
    return bool(res.data)


async def register_trial_school(payload: TrialRegisterIn) -> dict:
    """Create a trial school with one School Management login (SCH)."""
    client = get_client()

    school_email = payload.school_email.lower()

    if not is_verified(school_email, purpose="trial"):
        raise HTTPException(
            status_code=400,
            detail="School email not verified. Please verify via OTP before starting the trial.",
        )

    if await _email_taken(school_email):
        raise HTTPException(status_code=409, detail="This email is already registered")

    institution_code = await _next_institution_code(payload.school_name)
    school_user_code = await _next_school_login_user_code()

    now = datetime.now(timezone.utc)
    trial_ends = now + timedelta(days=TRIAL_DAYS)
    trial_ends_str = trial_ends.strftime("%d %b %Y at %I:%M %p UTC")

    school_row = {
        "institution_code": institution_code,
        "school_name": payload.school_name,
        "email": school_email,
        "phone": payload.phone.strip(),
        "principal_name": payload.admin_name.strip(),
        "admin_email": school_email,
        "admin_mobile": payload.phone.strip(),
        "subscription_plan": "trial",
        "is_active": True,
        "is_trial": True,
        "trial_starts_at": now.isoformat(),
        "trial_ends_at": trial_ends.isoformat(),
        "trial_admin_name": payload.admin_name.strip(),
        "trial_phone": payload.phone.strip(),
        "trial_status": "active",
    }

    optional_cols = ("is_trial", "trial_starts_at", "trial_ends_at", "trial_admin_name", "trial_phone", "trial_status", "admin_email", "admin_mobile")
    inserted = None
    last_exc = None
    row_copy = dict(school_row)
    for _ in range(len(optional_cols) + 1):
        try:
            inserted = await client.table("schools").insert(row_copy).execute()
            break
        except Exception as exc:
            last_exc = exc
            dropped = False
            for col in optional_cols:
                if col in row_copy:
                    row_copy.pop(col, None)
                    dropped = True
                    break
            if not dropped:
                raise
    if inserted is None:
        raise last_exc or HTTPException(status_code=500, detail="Failed to create trial school")
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Failed to create trial school")
    school = inserted.data[0]
    school_id = school["id"]

    school_password = generate_temp_password()
    password_hash = hash_password(school_password)

    school_login_row = {
        "school_id": school_id,
        "email": school_email,
        "full_name": payload.admin_name.strip(),
        "role": "school_admin",
        "user_code": school_user_code,
        "mobile": payload.phone.strip(),
        "password_hash": password_hash,
        "must_change_password": True,
        "is_active": True,
    }

    try:
        school_inserted = await client.table("users").insert(school_login_row).execute()
        if not school_inserted.data:
            raise HTTPException(status_code=500, detail="Failed to create school login account")
    except HTTPException:
        await client.table("schools").delete().eq("id", school_id).execute()
        raise
    except Exception as exc:
        await client.table("users").delete().eq("school_id", school_id).execute()
        await client.table("schools").delete().eq("id", school_id).execute()
        logger.error("User creation failed, rolled back trial school %s: %s", school_id, exc)
        raise HTTPException(status_code=500, detail="Failed to create school login account")

    email_body = build_trial_welcome_email(
        school_name=payload.school_name,
        admin_name=payload.admin_name,
        institution_code=institution_code,
        school_email=school_email,
        temp_password=school_password,
        trial_ends_at=trial_ends_str,
    )

    await send_email(
        school_email,
        "Welcome to Eduspace Free Trial – Your Demo School Login Credentials",
        email_body,
    )

    return {"institution_code": institution_code}


async def check_and_expire_trials() -> int:
    """Check for expired trials, deactivate users, and send expiry emails. Returns count expired."""
    client = get_client()
    now = datetime.now(timezone.utc)

    res = (
        await client.table("schools")
        .select("id,school_name,institution_code,trial_ends_at,trial_admin_name,email,trial_status")
        .eq("is_trial", True)
        .eq("trial_status", "active")
        .lt("trial_ends_at", now.isoformat())
        .execute()
    )

    expired_count = 0
    for school in res.data or []:
        school_id = school["id"]
        try:
            # Deactivate students and staff only.
            # Teachers remain active so they can still add students and perform duties.
            await client.table("users").update({"is_active": False}).eq("school_id", school_id).in_("role", ["student", "office_staff", "vice_principal"]).execute()
            # Mark trial as expired but keep school is_active so admin can still log in
            await client.table("schools").update({"trial_status": "expired"}).eq("id", school_id).execute()

            admin_name = school.get("trial_admin_name") or "Admin"
            email_body = build_trial_expired_email(
                school_name=school.get("school_name", ""),
                admin_name=admin_name,
                institution_code=school.get("institution_code", ""),
            )
            await send_email(
                school.get("email", ""),
                "Your Eduspace Free Trial Has Expired",
                email_body,
            )
            expired_count += 1
            logger.info("Trial expired for school %s (%s)", school_id, school.get("institution_code"))
        except Exception as exc:
            logger.error("Failed to expire trial school %s: %s", school_id, exc)

    return expired_count


async def get_trial_status(school_id: str) -> dict:
    """Get trial status for a school."""
    client = get_client()
    res = (
        await client.table("schools")
        .select("is_trial,trial_status,trial_ends_at,school_name,institution_code")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {"is_trial": False, "trial_status": None, "trial_ends_at": None, "school_name": None, "institution_code": None}
    row = res.data[0]
    return {
        "is_trial": row.get("is_trial", False),
        "trial_status": row.get("trial_status"),
        "trial_ends_at": str(row["trial_ends_at"])[:10] if row.get("trial_ends_at") else None,
        "school_name": row.get("school_name"),
        "institution_code": row.get("institution_code"),
    }


async def convert_trial_to_permanent(school_id: str) -> dict:
    """Convert a trial school to a permanent school. Keep all data."""
    client = get_client()
    res = (
        await client.table("schools")
        .select("id,is_trial,trial_status")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="School not found")
    row = res.data[0]
    if not row.get("is_trial"):
        raise HTTPException(status_code=400, detail="This school is not a trial school")

    await client.table("schools").update({
        "is_trial": False,
        "trial_status": "converted",
        "subscription_plan": "free",
        "is_active": True,
    }).eq("id", school_id).execute()

    await client.table("users").update({"is_active": True}).eq("school_id", school_id).execute()

    return {"message": "Trial converted to permanent account successfully"}


async def stop_trial_and_delete(school_id: str) -> dict:
    """Stop trial and delete all school data."""
    client = get_client()
    res = (
        await client.table("schools")
        .select("id,is_trial")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="School not found")
    row = res.data[0]
    if not row.get("is_trial"):
        raise HTTPException(status_code=400, detail="This school is not a trial school")

    tables_with_school_id = [
        "users", "students", "teachers", "staff", "attendance",
        "examinations", "fee_structures", "fee_payments", "announcements",
        "homework", "timetable", "schedule", "messages", "gallery",
        "leave_requests", "appointments", "library_books", "library_loans",
        "syllabus", "achievements", "expenses", "expense_transactions",
        "expense_savings", "calendar_events", "class_sections", "classes",
        "subjects", "academic_sessions", "student_settings", "school_medical_visits",
        "teacher_medical_visits", "payment_gateways", "fee_receipts",
        "class_section_fees", "teacher_substitute_assignments",
        "class_section_period_assignments", "school_periods",
    ]

    for table in tables_with_school_id:
        try:
            await client.table(table).delete().eq("school_id", school_id).execute()
        except Exception:
            pass

    await client.table("schools").delete().eq("id", school_id).execute()

    return {"message": "Trial stopped and all school data has been permanently deleted"}
