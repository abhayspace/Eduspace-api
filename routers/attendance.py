"""Attendance records (scoped per school)."""
from datetime import date, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from database import get_client
from schemas.content import (
    Announcement,
    AttendanceRec,
    ClassStudentAttendanceMarkIn,
    ClassStudentAttendanceOut,
    StaffAttendanceMarkIn,
    StaffAttendanceOut,
    StaffAttendanceSummaryOut,
)
from services import class_student_attendance_service, staff_attendance_service
from services.notification_service import notify_school
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/attendance", tags=["attendance"])

_COLUMNS = "id,school_id,student_email,class_name,date,status"
_STAFF_MARK_ROLES = ("teacher", "principal", "school_admin", "vice_principal", "super_admin")


async def _student_email_for_user(user: dict) -> str:
    """Resolve the attendance student_email — parents map to their linked child."""
    if user.get("role") != "parent":
        return user["email"]
    client = get_client()
    link = (
        await client.table("parents")
        .select("student_id")
        .eq("school_id", user["school_id"])
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    if not link.data:
        return user["email"]
    student = (
        await client.table("students")
        .select("user_id")
        .eq("id", link.data[0]["student_id"])
        .limit(1)
        .execute()
    )
    if not student.data:
        return user["email"]
    student_user = (
        await client.table("users")
        .select("email")
        .eq("id", student.data[0]["user_id"])
        .limit(1)
        .execute()
    )
    return student_user.data[0]["email"] if student_user.data else user["email"]


@router.get("/me", response_model=List[AttendanceRec])
async def my_attendance(user: dict = Depends(current_user)) -> List[AttendanceRec]:
    client = get_client()
    res = (
        await client.table("attendance")
        .select(_COLUMNS)
        .eq("school_id", user["school_id"])
        .eq("student_email", await _student_email_for_user(user))
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


# ── Holiday confirmation ──────────────────────────────────────────────
_ADMIN_ROLES = ("school_admin", "principal", "vice_principal", "super_admin")


class HolidayCheckOut(BaseModel):
    has_holiday_tomorrow: bool
    holiday_title: Optional[str] = None
    holiday_date: Optional[str] = None
    already_confirmed: bool = False


class HolidayConfirmIn(BaseModel):
    holiday_date: str
    holiday_title: str = "Holiday"


@router.get("/holiday-check", response_model=HolidayCheckOut)
async def check_tomorrow_holiday(
    user: dict = Depends(require_roles(*_ADMIN_ROLES)),
) -> HolidayCheckOut:
    """Check if tomorrow is a holiday in the school calendar and whether
    an announcement has already been created for it."""
    school_id = user["school_id"]
    tomorrow = (date.today() + timedelta(days=1)).isoformat()

    client = get_client()
    # Check if tomorrow is a holiday
    res = (
        await client.table("school_calendar_events")
        .select("title,event_date,end_date")
        .eq("school_id", school_id)
        .eq("event_type", "holiday")
        .lte("event_date", tomorrow)
        .gte("end_date", tomorrow)
        .limit(1)
        .execute()
    )
    if not res.data:
        res = (
            await client.table("school_calendar_events")
            .select("title,event_date,end_date")
            .eq("school_id", school_id)
            .eq("event_type", "holiday")
            .eq("event_date", tomorrow)
            .limit(1)
            .execute()
        )
    if not res.data:
        return HolidayCheckOut(has_holiday_tomorrow=False)

    holiday_title = res.data[0].get("title") or "Holiday"

    # Check if an announcement was already created for this holiday
    today_start = f"{date.today()}T00:00:00+00:00"
    today_end = f"{date.today()}T23:59:59.999999+00:00"
    ann_res = (
        await client.table("announcements")
        .select("id")
        .eq("school_id", school_id)
        .ilike("title", f"%{holiday_title}%")
        .gte("created_at", today_start)
        .lte("created_at", today_end)
        .limit(1)
        .execute()
    )
    already_confirmed = bool(ann_res.data)

    return HolidayCheckOut(
        has_holiday_tomorrow=True,
        holiday_title=holiday_title,
        holiday_date=tomorrow,
        already_confirmed=already_confirmed,
    )


@router.post("/holiday-confirm", response_model=Announcement)
async def confirm_holiday(
    body: HolidayConfirmIn,
    user: dict = Depends(require_roles(*_ADMIN_ROLES)),
) -> Announcement:
    """Confirm a holiday by creating an announcement for all teachers and students.
    This ensures attendance is not counted as a working day."""
    school_id = user["school_id"]
    client = get_client()

    # Check if announcement already exists for today
    today_start = f"{date.today()}T00:00:00+00:00"
    today_end = f"{date.today()}T23:59:59.999999+00:00"
    existing = (
        await client.table("announcements")
        .select("id")
        .eq("school_id", school_id)
        .ilike("title", f"%{body.holiday_title}%")
        .gte("created_at", today_start)
        .lte("created_at", today_end)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "Holiday announcement already created")

    title = f"Holiday Confirmation: {body.holiday_title}"
    body_text = (
        f"This is to confirm that {body.holiday_date} is a holiday ({body.holiday_title}).\n"
        f"Attendance will not be marked on this day.\n"
        f"Enjoy your day off!"
    )

    row = {
        "school_id": school_id,
        "title": title,
        "body": body_text,
        "audience": "all",
        "author": user.get("full_name") or "School Admin",
    }
    inserted = await client.table("announcements").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create announcement")

    created = Announcement(**inserted.data[0])
    await notify_school(school_id, f"Holiday Confirmation: {body.holiday_title}", body_text)
    return created


class DayHolidayCheckOut(BaseModel):
    is_holiday: bool
    holiday_title: Optional[str] = None
    holiday_id: Optional[str] = None


@router.get("/day-holiday-check", response_model=DayHolidayCheckOut)
async def check_day_holiday(
    day: str = Query(..., description="YYYY-MM-DD"),
    user: dict = Depends(require_roles(*_ADMIN_ROLES)),
) -> DayHolidayCheckOut:
    """Check if a specific date is a holiday in the school calendar."""
    school_id = user["school_id"]
    client = get_client()

    res = (
        await client.table("school_calendar_events")
        .select("id,title,event_date,end_date")
        .eq("school_id", school_id)
        .eq("event_type", "holiday")
        .lte("event_date", day)
        .gte("end_date", day)
        .limit(1)
        .execute()
    )
    if not res.data:
        res = (
            await client.table("school_calendar_events")
            .select("id,title,event_date,end_date")
            .eq("school_id", school_id)
            .eq("event_type", "holiday")
            .eq("event_date", day)
            .limit(1)
            .execute()
        )
    if not res.data:
        return DayHolidayCheckOut(is_holiday=False)
    return DayHolidayCheckOut(
        is_holiday=True,
        holiday_title=res.data[0].get("title") or "Holiday",
        holiday_id=res.data[0].get("id"),
    )


class RemoveHolidayIn(BaseModel):
    holiday_id: str


@router.delete("/day-holiday")
async def remove_day_holiday(
    body: RemoveHolidayIn,
    user: dict = Depends(require_roles(*_ADMIN_ROLES)),
):
    """Remove a holiday event from the school calendar (make it a working day)."""
    school_id = user["school_id"]
    client = get_client()

    deleted = (
        await client.table("school_calendar_events")
        .delete()
        .eq("id", body.holiday_id)
        .eq("school_id", school_id)
        .eq("event_type", "holiday")
        .execute()
    )
    if not deleted.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Holiday event not found")
    return {"ok": True, "message": "Holiday removed. The day is now a working day."}
