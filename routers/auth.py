"""Authentication routes: login, current user, and direct user registration."""
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from database import get_client
from schemas.auth import ChangePasswordIn, LoginIn, RegisterIn, TokenOut, UserPublic
from schemas.common import LOGIN_ROLES, ROLES
from schemas.forgot import LinkEmailIn
from services import teacher_service
from routers.forgot import is_gmail
from utils.deps import current_user, current_user_allow_expired
from utils.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("eduspace.auth")

_LOGIN_COLUMNS = (
    "id,email,full_name,role,school_id,admission_no,user_code,is_active,password_hash,must_change_password,gender"
)


def _admission_match_clauses(ident: str) -> list[str]:
    """Build PostgREST OR clauses for admission number login (with/without leading zeros)."""
    ident = ident.strip()
    clauses = [f"admission_no.eq.{ident}"]
    if ident.isdigit():
        n = int(ident)
        for candidate in {ident, str(n), f"{n:04d}", f"{n:05d}"}:
            clauses.append(f"admission_no.eq.{candidate}")
    else:
        clauses.append(f"admission_no.eq.{ident.upper()}")
    return list(dict.fromkeys(clauses))


def _to_public(user: dict) -> UserPublic:
    return UserPublic(
        id=user["id"],
        email=user["email"],
        full_name=user["full_name"],
        role=user["role"],
        school_id=user["school_id"],
        admission_no=user.get("admission_no"),
        user_code=user.get("user_code"),
        is_active=user.get("is_active", True),
        gender=user.get("gender"),
    )


async def _school_management_actor_ids(school_id: str) -> list[str]:
    client = get_client()
    res = (
        await client.table("users")
        .select("id,user_code,role")
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .execute()
    )
    ids: list[str] = []
    for row in res.data or []:
        code = (row.get("user_code") or "").strip().upper()
        if code.startswith("SCH") or code.startswith("ADM"):
            ids.append(row["id"])
    return ids


async def _to_public_enriched(user: dict) -> UserPublic:
    base = _to_public(user)
    updates: dict = {}
    code = (user.get("user_code") or "").strip().upper()
    if user.get("role") == "school_admin" and (code.startswith("SCH") or code.startswith("ADM")):
        actor_ids = await _school_management_actor_ids(user["school_id"])
        updates["message_actor_ids"] = actor_ids or [user["id"]]
    if user.get("role") == "teacher":
        info = await teacher_service.get_user_class_teacher_info(user["school_id"], user["id"])
        updates.update(info)
    # Check trial status
    school_id = user.get("school_id")
    if school_id:
        client = get_client()
        try:
            school_res = (
                await client.table("schools")
                .select("is_trial,trial_status,trial_ends_at")
                .eq("id", school_id)
                .limit(1)
                .execute()
            )
            if school_res.data:
                school_row = school_res.data[0]
                is_trial = school_row.get("is_trial", False)
                trial_status = school_row.get("trial_status")
                updates["is_trial"] = is_trial
                updates["trial_status"] = trial_status
                # Only show trial_expired blocking screen for school_admin
                updates["trial_expired"] = is_trial and trial_status == "expired" and user.get("role") == "school_admin"
        except Exception:
            pass
    return base.model_copy(update=updates) if updates else base


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn) -> TokenOut:
    client = get_client()
    user = None
    # School Management portal: resolve SCH*/ADM* without a user id.
    portal_role = (body.role or "").strip()
    is_school_portal_login = portal_role in {"office_staff", "school_admin"} and not (
        body.identifier or ""
    ).strip()

    if is_school_portal_login and body.school_id:
        # School Management login: SCH account only (User Type Admin in the app).
        # Legacy ADM accounts are accepted only when no SCH row exists.
        school_res = (
            await client.table("users")
            .select(_LOGIN_COLUMNS)
            .eq("school_id", body.school_id)
            .eq("role", "school_admin")
            .like("user_code", "SCH%")
            .limit(1)
            .execute()
        )
        user = school_res.data[0] if school_res.data else None
        if not user:
            legacy = (
                await client.table("users")
                .select(_LOGIN_COLUMNS)
                .eq("school_id", body.school_id)
                .eq("role", "school_admin")
                .like("user_code", "ADM%")
                .limit(1)
                .execute()
            )
            user = legacy.data[0] if legacy.data else None
        if not user or not verify_password(body.password, user.get("password_hash", "")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    elif body.identifier and body.school_id:
        ident = body.identifier.strip()
        adm_clauses = _admission_match_clauses(ident)
        or_parts = [
            f"email.eq.{ident.lower()}",
            f"user_code.eq.{ident.upper()}",
            *adm_clauses,
        ]
        query = (
            client.table("users")
            .select(_LOGIN_COLUMNS)
            .eq("school_id", body.school_id)
            .or_(",".join(or_parts))
        )
        if body.role:
            query = query.eq("role", body.role)
        res = await query.limit(1).execute()
        user = res.data[0] if res.data else None
        if not user or not verify_password(body.password, user.get("password_hash", "")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    elif body.email:
        res = (
            await client.table("users")
            .select(_LOGIN_COLUMNS)
            .eq("email", body.email.lower())
            .limit(1)
            .execute()
        )
        user = res.data[0] if res.data else None
        if not user or not verify_password(body.password, user.get("password_hash", "")):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    else:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")

    if not user.get("is_active", True):
        # Check if inactive due to expired trial
        school_id = user.get("school_id")
        if school_id:
            client = get_client()
            try:
                school_res = (
                    await client.table("schools")
                    .select("is_trial,trial_status")
                    .eq("id", school_id)
                    .limit(1)
                    .execute()
                )
                if school_res.data and school_res.data[0].get("is_trial") and school_res.data[0].get("trial_status") == "expired":
                    # Teachers should remain active even after trial expiry
                    if user.get("role") == "teacher":
                        await client.table("users").update({"is_active": True}).eq("id", user["id"]).execute()
                        user["is_active"] = True
                    else:
                        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your free trial has expired. Please register or stop to continue.")
            except HTTPException:
                raise
            except Exception:
                pass
        if not user.get("is_active", True):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Inactive user")
    if body.school_id and user.get("school_id") != body.school_id:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User does not belong to selected school")
    if body.role and not is_school_portal_login and user.get("role") != body.role:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Role does not match this account")

    token = create_access_token(
        user_id=user["id"], role=user["role"], email=user["email"], school_id=user["school_id"]
    )
    return TokenOut(access_token=token, user=await _to_public_enriched(user))


@router.post("/register", response_model=UserPublic)
async def register(body: RegisterIn) -> UserPublic:
    if body.role not in ROLES or body.role == "super_admin":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role")
    if body.role not in LOGIN_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid role")

    client = get_client()

    school = (
        await client.table("schools").select("id").eq("id", body.school_id).limit(1).execute()
    )
    if not school.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid school")

    existing = (
        await client.table("users")
        .select("id")
        .eq("school_id", body.school_id)
        .eq("email", body.email.lower())
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    row = {
        "email": body.email.lower(),
        "full_name": body.full_name,
        "role": body.role,
        "school_id": body.school_id,
        "is_active": True,
        "password_hash": hash_password(body.password),
    }
    inserted = await client.table("users").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create user")
    return _to_public(inserted.data[0])


@router.get("/me", response_model=UserPublic)
async def me(user: dict = Depends(current_user)) -> UserPublic:
    return await _to_public_enriched(user)


@router.post("/refresh", response_model=TokenOut)
async def refresh_token(user: dict = Depends(current_user_allow_expired)) -> TokenOut:
    """Issue a fresh token for an authenticated user (extends session).

    Accepts expired tokens — signature is still verified, and the user must
    still exist and be active. This prevents next-day logouts.
    """
    token = create_access_token(
        user_id=user["id"], role=user["role"], email=user["email"], school_id=user["school_id"]
    )
    return TokenOut(access_token=token, user=await _to_public_enriched(user))


@router.post("/change-password")
async def change_password(
    body: ChangePasswordIn,
    user: dict = Depends(current_user),
) -> dict:
    client = get_client()
    res = (
        await client.table("users")
        .select("password_hash,role,school_id,user_code")
        .eq("id", user["id"])
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    row = res.data[0]
    stored_hash = row.get("password_hash", "")
    if not verify_password(body.current_password, stored_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")

    new_hash = hash_password(body.new_password)
    payload = {
        "password_hash": new_hash,
        "login_password": body.new_password,
        "must_change_password": False,
    }
    await client.table("users").update(payload).eq("id", user["id"]).execute()
    return {"message": "Password updated"}


@router.put("/me/email", response_model=UserPublic)
async def link_email(
    body: LinkEmailIn,
    user: dict = Depends(current_user),
) -> UserPublic:
    """Link or update the signed-in user's email (students use this for Gmail)."""
    email = str(body.email).strip().lower()
    if user.get("role") == "student" and not is_gmail(email):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Please enter a valid Gmail address (e.g. you@gmail.com).",
        )

    client = get_client()
    existing = (
        await client.table("users")
        .select("id")
        .eq("school_id", user["school_id"])
        .eq("email", email)
        .neq("id", user["id"])
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "This email is already linked to another account.")

    updated = (
        await client.table("users")
        .update({"email": email})
        .eq("id", user["id"])
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return await _to_public_enriched(updated.data[0])
