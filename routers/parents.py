"""Parent directory (scoped per school)."""
from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from database import get_client
from schemas.auth import UserPublic
from utils.deps import require_roles

router = APIRouter(prefix="/parents", tags=["parents"])


class FeesAccessIn(BaseModel):
    allowed: bool

_COLUMNS = "id,email,full_name,role,school_id,admission_no,user_code,is_active"


@router.get("", response_model=List[UserPublic])
async def list_parents(
    user: dict = Depends(require_roles("school_admin", "principal", "teacher")),
) -> List[UserPublic]:
    client = get_client()
    res = (
        await client.table("users")
        .select(_COLUMNS)
        .eq("school_id", user["school_id"])
        .eq("role", "parent")
        .order("full_name")
        .limit(500)
        .execute()
    )
    return [UserPublic(**row) for row in (res.data or [])]


@router.get("/me/fees-access")
async def get_my_fees_access(
    user: dict = Depends(require_roles("parent")),
) -> dict:
    """Whether this parent allows the linked student(s) to see Fees (default on)."""
    try:
        res = (
            await get_client()
            .table("users")
            .select("allow_student_fees_access")
            .eq("id", user["id"])
            .limit(1)
            .execute()
        )
        allowed = bool((res.data or [{}])[0].get("allow_student_fees_access", True))
    except Exception:
        # Column missing (migration not applied yet) — default to allowed.
        allowed = True
    return {"allowed": allowed}


@router.put("/me/fees-access")
async def set_my_fees_access(
    body: FeesAccessIn,
    user: dict = Depends(require_roles("parent")),
) -> dict:
    await (
        get_client()
        .table("users")
        .update({"allow_student_fees_access": body.allowed})
        .eq("id", user["id"])
        .execute()
    )
    return {"allowed": body.allowed}
