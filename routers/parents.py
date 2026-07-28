"""Parent directory (scoped per school)."""
from typing import List

from fastapi import APIRouter, Depends

from database import get_client
from schemas.auth import UserPublic
from utils.deps import require_roles

router = APIRouter(prefix="/parents", tags=["parents"])

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
