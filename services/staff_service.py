"""Non-teaching staff and admin role provisioning."""
import logging
from typing import Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.people import AdminRoleCreateIn, AdminRoleOut, StaffCreateIn, StaffCreateOut, CredentialsOut
from utils.codes import generate_employee_no, generate_temp_password, generate_user_code
from utils.security import hash_password

logger = logging.getLogger("eduspace.staff")

STAFF_ROLES = {
    "receptionist",
    "accountant",
    "librarian",
    "hostel_manager",
    "transport_manager",
    "school_doctor",
}
ADMIN_ROLES = {"principal", "vice_principal"}
ALL_STAFF_CREATE_ROLES = STAFF_ROLES | ADMIN_ROLES

_ROLE_DEPARTMENTS = {
    "receptionist": "Front Office",
    "accountant": "Finance",
    "librarian": "Library",
    "hostel_manager": "Hostel",
    "transport_manager": "Transport",
    "school_doctor": "Medical",
    "principal": "Administration",
    "vice_principal": "Administration",
}


async def _next_user_code(school_id: str, role: str) -> str:
    client = get_client()
    prefix_map = {
        "receptionist": "REC",
        "accountant": "ACC",
        "librarian": "LIB",
        "hostel_manager": "HST",
        "transport_manager": "TRN",
        "school_doctor": "DOC",
        "principal": "PRC",
        "vice_principal": "VPC",
    }
    prefix = prefix_map.get(role, "STF")
    res = (
        await client.table("users")
        .select("user_code")
        .eq("school_id", school_id)
        .eq("role", role)
        .like("user_code", f"{prefix}%")
        .execute()
    )
    nums = []
    for row in res.data or []:
        val = row.get("user_code") or ""
        try:
            nums.append(int(val[len(prefix):]))
        except (ValueError, IndexError):
            pass
    count = max(nums) if nums else 0
    return generate_user_code(role, count)


async def _next_employee_no(school_id: str, role: str) -> str:
    client = get_client()
    res = (
        await client.table("staff_profiles")
        .select("employee_no")
        .eq("school_id", school_id)
        .execute()
    )
    nums = []
    for row in res.data or []:
        val = row.get("employee_no") or ""
        try:
            nums.append(int(val.split("-")[-1]))
        except (ValueError, IndexError):
            pass
    count = max(nums) if nums else 0
    return generate_employee_no(role, count)


async def get_admin_role(school_id: str, role: str) -> AdminRoleOut:
    if role not in ADMIN_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid admin role")
    client = get_client()
    res = (
        await client.table("users")
        .select("id,full_name,email,role,user_code,mobile")
        .eq("school_id", school_id)
        .eq("role", role)
        .limit(1)
        .execute()
    )
    if not res.data:
        return AdminRoleOut(id="", full_name="", email="", role=role, exists=False)
    u = res.data[0]
    return AdminRoleOut(
        id=u["id"],
        full_name=u["full_name"],
        email=u["email"],
        role=u["role"],
        user_code=u.get("user_code"),
        mobile=u.get("mobile"),
        exists=True,
    )


async def create_or_update_admin_role(school_id: str, role: str, body: AdminRoleCreateIn) -> tuple[AdminRoleOut, Optional[CredentialsOut]]:
    if role not in ADMIN_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid admin role")
    client = get_client()
    existing = await get_admin_role(school_id, role)
    email = body.email.lower()
    credentials: Optional[CredentialsOut] = None

    if existing.exists:
        dup = (
            await client.table("users")
            .select("id")
            .eq("school_id", school_id)
            .eq("email", email)
            .neq("id", existing.id)
            .limit(1)
            .execute()
        )
        if dup.data:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")
        await client.table("users").update({
            "full_name": body.full_name,
            "email": email,
            "mobile": body.mobile,
            "gender": body.gender,
            "dob": body.dob.isoformat() if body.dob else None,
            "address": body.address,
            "photo_url": body.photo_url,
        }).eq("id", existing.id).execute()
        updated = await get_admin_role(school_id, role)
        return updated, None

    dup = (
        await client.table("users")
        .select("id")
        .eq("school_id", school_id)
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if dup.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user_code = await _next_user_code(school_id, role)
    temp_password = generate_temp_password()
    user_row = {
        "school_id": school_id,
        "email": email,
        "full_name": body.full_name,
        "role": role,
        "user_code": user_code,
        "mobile": body.mobile,
        "gender": body.gender,
        "dob": body.dob.isoformat() if body.dob else None,
        "address": body.address,
        "photo_url": body.photo_url,
        "password_hash": hash_password(temp_password),
        "must_change_password": True,
        "is_active": True,
    }
    ins = await client.table("users").insert(user_row).execute()
    if not ins.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create user")
    credentials = CredentialsOut(user_code=user_code, password=temp_password)
    created = await get_admin_role(school_id, role)
    return created, credentials


async def create_staff(school_id: str, body: StaffCreateIn) -> StaffCreateOut:
    if body.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid staff role")
    client = get_client()
    email = body.email.lower()

    existing = (
        await client.table("users")
        .select("id")
        .eq("school_id", school_id)
        .eq("email", email)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    user_code = await _next_user_code(school_id, body.role)
    employee_no = await _next_employee_no(school_id, body.role)
    temp_password = generate_temp_password()

    user_row = {
        "school_id": school_id,
        "email": email,
        "full_name": body.full_name,
        "role": body.role,
        "user_code": user_code,
        "mobile": body.mobile,
        "gender": body.gender,
        "dob": body.dob.isoformat() if body.dob else None,
        "address": body.address,
        "photo_url": body.photo_url,
        "password_hash": hash_password(temp_password),
        "must_change_password": True,
        "is_active": True,
    }
    user_ins = await client.table("users").insert(user_row).execute()
    if not user_ins.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create staff user")
    user = user_ins.data[0]

    profile_row = {
        "school_id": school_id,
        "user_id": user["id"],
        "employee_no": employee_no,
        "gender": body.gender,
        "dob": body.dob.isoformat() if body.dob else None,
        "address": body.address,
        "photo_url": body.photo_url,
        "qualification": body.qualification,
        "experience_years": body.experience_years,
        "joining_date": body.joining_date.isoformat() if body.joining_date else None,
        "department": body.department or _ROLE_DEPARTMENTS.get(body.role),
    }
    try:
        await client.table("staff_profiles").insert(profile_row).execute()
    except Exception as exc:  # noqa: BLE001
        await client.table("users").delete().eq("id", user["id"]).execute()
        logger.error("Staff profile creation failed: %s", exc)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create staff profile")

    return StaffCreateOut(
        user_id=user["id"],
        full_name=user["full_name"],
        role=body.role,
        email=email,
        user_code=user_code,
        employee_no=employee_no,
        credentials=CredentialsOut(user_code=user_code, password=temp_password),
    )
