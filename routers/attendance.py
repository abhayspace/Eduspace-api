"""Attendance records (scoped per school)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from database import get_client
from schemas.content import (
    AttendanceRec,
    ClassStudentAttendanceMarkIn,
    ClassStudentAttendanceOut,
    StaffAttendanceMarkIn,
    StaffAttendanceOut,
    StaffAttendanceSummaryOut,
)
from services import class_student_attendance_service, staff_attendance_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/attendance", tags=["attendance"])

_COLUMNS = "id,school_id,student_email,class_name,date,status"
_STAFF_MARK_ROLES = ("teacher", "principal", "school_admin", "vice_principal", "super_admin")


@router.get("/me", response_model=List[AttendanceRec])
async def my_attendance(user: dict = Depends(current_user)) -> List[AttendanceRec]:
    client = get_client()
    res = (
        await client.table("attendance")
        .select(_COLUMNS)
        .eq("school_id", user["school_id"])
        .eq("student_email", user["email"])
        .order("date", desc=True)
        .limit(100)
        .execute()
    )
    return [AttendanceRec(**row) for row in (res.data or [])]


@router.get("/student/{student_id}", response_model=List[AttendanceRec])
async def student_attendance_history(
    student_id: str,
    limit: int = Query(100, ge=1, le=365),
    user: dict = Depends(
        require_roles(
            "school_admin",
            "principal",
            "vice_principal",
            "teacher",
            "super_admin",
            "office_staff",
        )
    ),
) -> List[AttendanceRec]:
    """Staff/admin: attendance history for one student (by linked user email)."""
    client = get_client()
    school_id = user["school_id"]
    profile = (
        await client.table("students")
        .select("id,user_id")
        .eq("school_id", school_id)
        .eq("id", student_id)
        .limit(1)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    user_id = profile.data[0].get("user_id")
    if not user_id:
        return []
    user_row = (
        await client.table("users")
        .select("email")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    email = ((user_row.data or [{}])[0].get("email") or "").strip().lower()
    if not email:
        return []
    res = (
        await client.table("attendance")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("student_email", email)
        .order("date", desc=True)
        .limit(limit)
        .execute()
    )
    return [AttendanceRec(**row) for row in (res.data or [])]


@router.get("/teacher/{teacher_id}", response_model=List[StaffAttendanceOut])
async def teacher_attendance_history(
    teacher_id: str,
    limit: int = Query(100, ge=1, le=365),
    user: dict = Depends(require_roles(*_STAFF_MARK_ROLES)),
) -> List[StaffAttendanceOut]:
    """Staff/admin: attendance history for one teacher."""
    client = get_client()
    school_id = user["school_id"]
    profile = (
        await client.table("teachers")
        .select("id,user_id")
        .eq("school_id", school_id)
        .eq("id", teacher_id)
        .limit(1)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    user_id = profile.data[0].get("user_id")
    if not user_id:
        return []
    return await staff_attendance_service.list_staff_attendance_for_user(
        school_id,
        user_id,
        limit=limit,
    )


@router.post("", response_model=AttendanceRec)
async def mark_attendance(
    body: AttendanceRec,
    user: dict = Depends(require_roles("teacher", "principal", "school_admin")),
) -> AttendanceRec:
    client = get_client()
    row = {
        "school_id": user["school_id"],
        "student_email": body.student_email,
        "class_name": body.class_name,
        "date": body.date,
        "status": body.status,
        "marked_by": user["full_name"],
    }
    inserted = await client.table("attendance").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to mark attendance")
    return AttendanceRec(**inserted.data[0])


@router.get("/staff", response_model=List[StaffAttendanceOut])
async def list_staff_attendance(
    date: Optional[str] = Query(None, description="Attendance date (YYYY-MM-DD)"),
    from_date: Optional[str] = Query(None, description="Range start (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Range end (YYYY-MM-DD)"),
    user: dict = Depends(require_roles(*_STAFF_MARK_ROLES)),
) -> List[StaffAttendanceOut]:
    if date:
        return await staff_attendance_service.list_staff_attendance_for_date(user["school_id"], date)
    if from_date and to_date:
        return await staff_attendance_service.list_staff_attendance_for_range(
            user["school_id"],
            from_date,
            to_date,
        )
    raise HTTPException(
        status.HTTP_400_BAD_REQUEST,
        "Provide either date or both from_date and to_date",
    )


@router.post("/staff", response_model=StaffAttendanceOut)
async def mark_staff_attendance(
    body: StaffAttendanceMarkIn,
    user: dict = Depends(require_roles(*_STAFF_MARK_ROLES)),
) -> StaffAttendanceOut:
    marked_by = user.get("full_name") or user.get("email") or "Admin"
    return await staff_attendance_service.mark_staff_attendance(
        user["school_id"],
        body,
        marked_by,
    )


@router.get("/my-class", response_model=ClassStudentAttendanceOut)
async def list_my_class_attendance(
    date: str = Query(..., description="Attendance date (YYYY-MM-DD)"),
    user: dict = Depends(require_roles("teacher")),
) -> ClassStudentAttendanceOut:
    return await class_student_attendance_service.list_my_class_attendance(user, date)


@router.post("/my-class", response_model=ClassStudentAttendanceOut)
async def mark_my_class_attendance(
    body: ClassStudentAttendanceMarkIn,
    user: dict = Depends(require_roles("teacher")),
) -> ClassStudentAttendanceOut:
    await class_student_attendance_service.mark_my_class_attendance(user, body)
    return await class_student_attendance_service.list_my_class_attendance(user, body.date)


@router.get("/my-class-report")
async def my_class_attendance_report(
    user: dict = Depends(require_roles("teacher")),
    days: int = Query(28, ge=1, le=31),
) -> dict:
    return await class_student_attendance_service.my_class_attendance_report(user, days=days)


@router.get("/class-section-report")
async def class_section_attendance_report(
    class_name: str = Query(..., min_length=1),
    section_name: str = Query(""),
    days: int = Query(1, ge=1, le=31),
    user: dict = Depends(
        require_roles("teacher", "school_admin", "principal", "vice_principal", "super_admin")
    ),
) -> dict:
    return await class_student_attendance_service.class_section_attendance_report(
        user,
        class_name=class_name,
        section_name=section_name,
        days=days,
    )


@router.get("/my-staff-summary", response_model=StaffAttendanceSummaryOut)
async def my_staff_attendance_summary(
    user: dict = Depends(require_roles("teacher")),
    view: str = Query("monthly", description="monthly or yearly"),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=1970, le=2100),
) -> StaffAttendanceSummaryOut:
    return await staff_attendance_service.my_staff_attendance_summary(
        user,
        view=view,
        month=month,
        year=year,
    )


@router.get("/my-student-summary", response_model=StaffAttendanceSummaryOut)
async def my_student_attendance_summary(
    user: dict = Depends(require_roles("student")),
    view: str = Query("monthly", description="monthly or yearly"),
    month: Optional[int] = Query(None, ge=1, le=12),
    year: Optional[int] = Query(None, ge=1970, le=2100),
) -> StaffAttendanceSummaryOut:
    return await staff_attendance_service.my_student_attendance_summary(
        user,
        view=view,
        month=month,
        year=year,
    )
