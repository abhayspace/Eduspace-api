"""Student module settings routes."""
from fastapi import APIRouter, Depends

from schemas.student_settings import StudentSettingsOut, StudentSettingsUpdateIn
from services import student_settings_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/students/settings", tags=["student-settings"])

_ADMIN_ROLES = ("school_admin", "principal", "vice_principal", "super_admin")


@router.get("", response_model=StudentSettingsOut)
async def get_student_settings(user: dict = Depends(current_user)) -> StudentSettingsOut:
    return await student_settings_service.get_settings(user["school_id"])


@router.put("", response_model=StudentSettingsOut)
async def update_student_settings(
    body: StudentSettingsUpdateIn,
    user: dict = Depends(require_roles(*_ADMIN_ROLES)),
) -> StudentSettingsOut:
    return await student_settings_service.update_settings(user["school_id"], body)
