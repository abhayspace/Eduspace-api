"""Student module settings: toggles for class-teacher add and approval requirement."""
from fastapi import HTTPException, status

from database import get_client
from schemas.student_settings import StudentSettingsOut, StudentSettingsUpdateIn


async def get_settings(school_id: str) -> StudentSettingsOut:
    client = get_client()
    res = (
        await client.table("schools")
        .select("class_teacher_can_add_student,student_approval_required")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    row = rows[0]
    return StudentSettingsOut(
        class_teacher_can_add_student=bool(row.get("class_teacher_can_add_student", True)),
        student_approval_required=bool(row.get("student_approval_required", True)),
    )


async def update_settings(school_id: str, body: StudentSettingsUpdateIn) -> StudentSettingsOut:
    client = get_client()
    res = (
        await client.table("schools")
        .update(
            {
                "class_teacher_can_add_student": body.class_teacher_can_add_student,
                "student_approval_required": body.student_approval_required,
            }
        )
        .eq("id", school_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return await get_settings(school_id)
    row = rows[0]
    return StudentSettingsOut(
        class_teacher_can_add_student=bool(row.get("class_teacher_can_add_student", True)),
        student_approval_required=bool(row.get("student_approval_required", True)),
    )
