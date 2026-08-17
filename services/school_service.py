"""Business logic for school self-service registration."""
import logging

from fastapi import HTTPException

from database import get_client
from schemas.school import SchoolRegisterIn
from services.email_service import (
    build_school_welcome_email,
    send_email,
)
from services.otp_service import is_verified
from services.school_logo_service import save_school_logo_base64
from utils.codes import (
    generate_school_login_user_code,
    generate_temp_password,
    generate_unique_code_variants,
)
from utils.security import hash_password

logger = logging.getLogger("eduspace.school")


async def _next_institution_code(school_name: str) -> str:
    """Return the first unique institution code for the given school name."""
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
    """Return the next sequential SCH*** code for institutional school login accounts."""
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


async def register_school(payload: SchoolRegisterIn) -> dict:
    """Create a school with one School Management login (SCH). Admin details are profile-only."""
    client = get_client()

    school_email = payload.school_email.lower()
    admin_email = payload.admin_email.lower()

    if school_email == admin_email:
        raise HTTPException(status_code=400, detail="School email and administrator email must be different")

    if not is_verified(school_email):
        raise HTTPException(
            status_code=400,
            detail="School email not verified. Please verify via OTP before registering.",
        )
    if not is_verified(admin_email):
        raise HTTPException(
            status_code=400,
            detail="Administrator email not verified. Please verify via OTP before registering.",
        )

    if await _email_taken(school_email):
        raise HTTPException(status_code=409, detail="School email already registered")

    institution_code = await _next_institution_code(payload.school_name)
    school_user_code = await _next_school_login_user_code()
    phone_raw = (payload.school_phone or "").strip()
    primary_phone = phone_raw.split(",")[0].strip() if phone_raw else None
    admin_mobile = (payload.admin_mobile or "").strip() or None

    school_row = {
        "institution_code": institution_code,
        "school_name": payload.school_name,
        "school_type": payload.school_type,
        "board": payload.education_board,
        "level_of_education": payload.level_of_education,
        "total_students": payload.total_students,
        "total_teachers": payload.total_teachers,
        "academic_session": payload.academic_session,
        "email": school_email,
        "phone": phone_raw or None,
        "website": (payload.website or "").strip() or None,
        "established_date": (payload.established_date or "").strip() or None,
        "address": payload.address,
        "city": payload.city,
        "state": payload.state,
        "country": "India",
        "pincode": payload.pincode,
        "principal_name": payload.admin_full_name,
        "admin_email": admin_email,
        "admin_mobile": admin_mobile,
        "subscription_plan": "free",
        "is_active": True,
    }

    # Optional columns may be missing until migrations 041/043 are applied.
    optional_cols = ("established_date", "admin_email", "admin_mobile")
    inserted = None
    last_exc = None
    for _ in range(len(optional_cols) + 1):
        try:
            inserted = await client.table("schools").insert(school_row).execute()
            break
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            dropped = False
            for col in optional_cols:
                if col in school_row:
                    school_row.pop(col, None)
                    dropped = True
                    break
            if not dropped:
                raise
    if inserted is None:
        raise last_exc or HTTPException(status_code=500, detail="Failed to create school")
    if not inserted.data:
        raise HTTPException(status_code=500, detail="Failed to create school")
    school = inserted.data[0]
    school_id = school["id"]

    if payload.logo_base64:
        try:
            logo_url = save_school_logo_base64(
                school_id,
                payload.logo_base64,
                filename=payload.logo_filename,
                content_type=payload.logo_content_type,
            )
            await client.table("schools").update({"logo_url": logo_url}).eq("id", school_id).execute()
            school["logo_url"] = logo_url
        except HTTPException:
            await client.table("schools").delete().eq("id", school_id).execute()
            raise
        except Exception as exc:  # noqa: BLE001
            await client.table("schools").delete().eq("id", school_id).execute()
            logger.error("Logo upload failed for school %s: %s", school_id, exc)
            raise HTTPException(status_code=500, detail="Failed to save school logo")

    school_password = generate_temp_password()
    password_hash = hash_password(school_password)

    # Single login account: School Management (SCH). User-type tag in app is Admin.
    school_login_row = {
        "school_id": school_id,
        "email": school_email,
        "full_name": payload.admin_full_name.strip(),
        "role": "school_admin",
        "user_code": school_user_code,
        "mobile": admin_mobile or primary_phone,
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
    except Exception as exc:  # noqa: BLE001
        await client.table("users").delete().eq("school_id", school_id).execute()
        await client.table("schools").delete().eq("id", school_id).execute()
        logger.error("User creation failed, rolled back school %s: %s", school_id, exc)
        raise HTTPException(status_code=500, detail="Failed to create school login account")

    school_email_body = build_school_welcome_email(
        school_name=payload.school_name,
        institution_code=institution_code,
        school_email=school_email,
        temp_password=school_password,
        city=payload.city or "",
        state=payload.state or "",
        board=payload.education_board or "",
        school_type=payload.school_type or "",
    )

    await send_email(
        school_email,
        "Welcome to Eduspace – Your School Management Login Credentials",
        school_email_body,
    )

    return {"school_id": school_id, "institution_code": institution_code}
