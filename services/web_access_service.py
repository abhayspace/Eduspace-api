"""School-scoped website access-code account helpers."""
from datetime import datetime, timezone
import secrets

from fastapi import HTTPException, status

from database import get_client
from utils.security import hash_password, verify_password

_WEB_ACCESS_USER_CODE = "WEBACCESS"
_WEB_ACCESS_COLUMNS = (
    "id,email,full_name,role,school_id,admission_no,user_code,is_active,"
    "password_hash,must_change_password,gender,login_password,dob,mobile,"
    "address,occupation,alternate_mobile,web_access_only"
)


def generate_access_code() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


async def ensure_web_access_user(school_id: str) -> dict:
    client = get_client()
    res = (
        await client.table("users")
        .select(_WEB_ACCESS_COLUMNS)
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .eq("web_access_only", True)
        .limit(1)
        .execute()
    )
    if res.data:
        user = res.data[0]
        if not user.get("is_active", True):
            updated = (
                await client.table("users")
                .update({"is_active": True})
                .eq("id", user["id"])
                .execute()
            )
            if updated.data:
                user = updated.data[0]
        return user

    row = {
        "email": f"web-access-{school_id}@eduspace.local",
        "full_name": "Website Access",
        "role": "school_admin",
        "school_id": school_id,
        "user_code": _WEB_ACCESS_USER_CODE,
        "is_active": True,
        "web_access_only": True,
        "password_hash": hash_password(secrets.token_urlsafe(32)),
    }
    inserted = await client.table("users").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create website access account")
    return inserted.data[0]


async def save_access_code(school_id: str, code: str, created_by: str) -> None:
    await ensure_web_access_user(school_id)
    client = get_client()
    updated = (
        await client.table("schools")
        .update(
            {
                "web_access_code_hash": hash_password(code),
                "web_access_code_created_at": datetime.now(timezone.utc).isoformat(),
                "web_access_code_created_by": created_by,
            }
        )
        .eq("id", school_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")


async def get_access_code_status(school_id: str) -> dict:
    client = get_client()
    res = (
        await client.table("schools")
        .select("web_access_code_hash,web_access_code_created_at")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    row = res.data[0]
    return {
        "has_code": bool(row.get("web_access_code_hash")),
        "created_at": row.get("web_access_code_created_at"),
    }


async def user_for_access_code(school_id: str, code: str) -> dict:
    client = get_client()
    school = (
        await client.table("schools")
        .select("id,is_active,web_access_code_hash")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not school.data:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access code")
    row = school.data[0]
    if not row.get("is_active", True) or not verify_password(code, row.get("web_access_code_hash") or ""):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid access code")
    return await ensure_web_access_user(school_id)
