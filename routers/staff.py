"""Non-teaching staff and admin role management."""
from typing import Optional

from fastapi import APIRouter, Depends, status

from schemas.people import AdminRoleCreateIn, AdminRoleOut, StaffCreateIn, StaffCreateOut, CredentialsOut
from services import staff_service
from utils.deps import require_roles

router = APIRouter(prefix="/staff", tags=["staff"])


@router.post("", response_model=StaffCreateOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    body: StaffCreateIn,
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> StaffCreateOut:
    return await staff_service.create_staff(user["school_id"], body)


@router.get("/principal", response_model=AdminRoleOut)
async def get_principal(
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> AdminRoleOut:
    return await staff_service.get_admin_role(user["school_id"], "principal")


@router.post("/principal", response_model=dict)
async def upsert_principal(
    body: AdminRoleCreateIn,
    user: dict = Depends(require_roles("school_admin")),
) -> dict:
    admin, creds = await staff_service.create_or_update_admin_role(user["school_id"], "principal", body)
    out = {"admin": admin.model_dump()}
    if creds:
        out["credentials"] = creds.model_dump()
    return out


@router.get("/vice-principal", response_model=AdminRoleOut)
async def get_vice_principal(
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> AdminRoleOut:
    return await staff_service.get_admin_role(user["school_id"], "vice_principal")


@router.post("/vice-principal", response_model=dict)
async def upsert_vice_principal(
    body: AdminRoleCreateIn,
    user: dict = Depends(require_roles("school_admin")),
) -> dict:
    admin, creds = await staff_service.create_or_update_admin_role(user["school_id"], "vice_principal", body)
    out = {"admin": admin.model_dump()}
    if creds:
        out["credentials"] = creds.model_dump()
    return out
