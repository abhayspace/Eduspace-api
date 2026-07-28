"""Class-teacher student attendance (mark attendance for assigned class-section)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from typing import Dict, List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.content import (
    ClassStudentAttendanceItem,
    ClassStudentAttendanceMarkIn,
    ClassStudentAttendanceOut,
)
from services import student_service
from services.staff_attendance_service import ensure_attendance_date_allowed
from services.teacher_service import _resolve_class_names

_VALID_STATUSES = frozenset({"present", "absent", "leave"})


async def _class_teacher_profile(school_id: str, user_id: str) -> dict:
    client = get_client()
    res = (
        await client.table("teachers")
        .select("id,is_class_teacher,class_teacher_class_id,class_teacher_section_id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher profile not found")
    profile = res.data[0]
    if not profile.get("is_class_teacher"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Class teacher access required")
    if not profile.get("class_teacher_class_id") or not profile.get("class_teacher_section_id"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Class teacher assignment is incomplete")
    return profile


def _class_label(class_name: str, section_name: Optional[str]) -> str:
    if section_name:
        return f"{class_name}-{section_name}"
    return class_name


async def list_my_class_attendance(user: dict, attendance_date: str) -> ClassStudentAttendanceOut:
    school_id = user["school_id"]
    profile = await _class_teacher_profile(school_id, user["id"])
    class_id = profile["class_teacher_class_id"]
    section_id = profile["class_teacher_section_id"]
    normalized_date = ensure_attendance_date_allowed(attendance_date)

    students = await student_service.list_students(school_id, class_id, section_id)
    class_name = ""
    section_name = ""
    if students:
        class_name = students[0].class_name or ""
        section_name = students[0].section_name or ""
    else:
        class_name, section_name = await _resolve_class_names(school_id, class_id, section_id)
        class_name = class_name or ""
        section_name = section_name or ""

    if not students:
        return ClassStudentAttendanceOut(
            class_name=class_name,
            section_name=section_name,
            date=normalized_date,
            students=[],
        )

    class_label = _class_label(class_name, section_name)
    emails = [s.email for s in students if s.email]

    status_by_email: Dict[str, str] = {}
    if emails:
        client = get_client()
        res = (
            await client.table("attendance")
            .select("student_email,status")
            .eq("school_id", school_id)
            .eq("date", normalized_date)
            .eq("class_name", class_label)
            .in_("student_email", emails)
            .execute()
        )
        for row in res.data or []:
            status_value = row.get("status")
            if status_value in _VALID_STATUSES:
                status_by_email[row["student_email"]] = status_value

    items: List[ClassStudentAttendanceItem] = []
    for student in students:
        email = student.email or ""
        items.append(
            ClassStudentAttendanceItem(
                student_id=student.id,
                user_id=student.user_id,
                full_name=student.full_name,
                roll_no=student.roll_no,
                admission_no=student.admission_no,
                status=status_by_email.get(email),
            )
        )

    return ClassStudentAttendanceOut(
        class_name=class_name,
        section_name=section_name or "",
        date=normalized_date,
        students=items,
    )


async def mark_my_class_attendance(user: dict, body: ClassStudentAttendanceMarkIn) -> ClassStudentAttendanceItem:
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid attendance status")

    school_id = user["school_id"]
    profile = await _class_teacher_profile(school_id, user["id"])
    class_id = profile["class_teacher_class_id"]
    section_id = profile["class_teacher_section_id"]
    normalized_date = ensure_attendance_date_allowed(body.date)
    marked_by = user.get("full_name") or user.get("email") or "Class Teacher"

    student = await student_service.get_student(school_id, body.student_id)
    if student.class_id != class_id or student.section_id != section_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Student is not in your class")
    if not student.email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student has no login email")

    class_label = _class_label(student.class_name or "", student.section_name)
    client = get_client()
    existing = (
        await client.table("attendance")
        .select("id")
        .eq("school_id", school_id)
        .eq("student_email", student.email)
        .eq("date", normalized_date)
        .limit(1)
        .execute()
    )
    payload = {
        "status": body.status,
        "marked_by": marked_by,
        "class_name": class_label,
        "student_id": student.user_id,
    }
    if existing.data:
        updated = (
            await client.table("attendance")
            .update(payload)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
        if not updated.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update attendance")
    else:
        inserted = (
            await client.table("attendance")
            .insert(
                {
                    "school_id": school_id,
                    "student_email": student.email,
                    "date": normalized_date,
                    **payload,
                }
            )
            .execute()
        )
        if not inserted.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to mark attendance")

    return ClassStudentAttendanceItem(
        student_id=student.id,
        user_id=student.user_id,
        full_name=student.full_name,
        roll_no=student.roll_no,
        admission_no=student.admission_no,
        status=body.status,
    )


async def my_class_attendance_report(user: dict, days: int = 28) -> dict:
    school_id = user["school_id"]
    profile = await _class_teacher_profile(school_id, user["id"])
    class_id = profile["class_teacher_class_id"]
    section_id = profile["class_teacher_section_id"]

    students = await student_service.list_students(school_id, class_id, section_id)
    total_students = len(students)
    emails = [student.email for student in students if student.email]

    today = date.today()
    start = today - timedelta(days=days - 1)
    present_by_date: Dict[str, int] = defaultdict(int)

    if emails:
        client = get_client()
        res = (
            await client.table("attendance")
            .select("date, status, student_email")
            .eq("school_id", school_id)
            .gte("date", start.isoformat())
            .lte("date", today.isoformat())
            .in_("student_email", emails)
            .execute()
        )
        for row in res.data or []:
            if row.get("status") == "present":
                present_by_date[row["date"]] += 1

    points = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        key = d.isoformat()
        points.append(
            {
                "date": key,
                "present": present_by_date.get(key, 0),
                "label": str(d.day),
            }
        )

    payload: dict = {"points": points, "days": days}
    if days == 1:
        present = points[-1]["present"] if points else 0
        # Recount leave/absent for accurate daily summary when leave is used.
        leave_count = 0
        if emails:
            client = get_client()
            leave_res = (
                await client.table("attendance")
                .select("student_email")
                .eq("school_id", school_id)
                .eq("date", today.isoformat())
                .eq("status", "leave")
                .in_("student_email", emails)
                .execute()
            )
            leave_count = len(leave_res.data or [])
        absent = max(total_students - present - leave_count, 0)
        pct = round((present / total_students) * 100) if total_students else 0
        payload["summary"] = {
            "total": total_students,
            "present": present,
            "absent": absent,
            "pct": pct,
        }
    return payload


async def _resolve_class_section_ids(
    school_id: str, class_name: str, section_name: str
) -> tuple[str, str]:
    from services import academic_service

    class_key = (class_name or "").strip().lower()
    section_key = (section_name or "").strip().lower()
    if not class_key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Class name is required")

    classes = await academic_service.list_classes(school_id)
    match = next((row for row in classes if (row.name or "").strip().lower() == class_key), None)
    if not match:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    sections = match.sections or []
    if not section_key:
        if len(sections) == 1:
            return match.id, sections[0].id
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Section name is required")

    section = next(
        (row for row in sections if (row.name or "").strip().lower() == section_key),
        None,
    )
    if not section:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return match.id, section.id


def _teacher_teaches_class_section(
    assignments: list[str], class_name: str, section_name: str
) -> bool:
    class_key = (class_name or "").strip().lower()
    section_key = (section_name or "").strip().lower()
    if not class_key:
        return False
    specific = f"{class_key} - {section_key}"
    all_sections = f"{class_key} - all sections"
    for entry in assignments or []:
        value = (entry or "").strip().lower()
        if not value:
            continue
        if value == specific or value == all_sections:
            return True
        sep = " - "
        idx = value.rfind(sep)
        entry_class = value[:idx].strip() if idx > 0 else value
        if entry_class == class_key and not section_key:
            return True
    return False


async def assert_can_view_class_section(
    user: dict, class_name: str, section_name: str
) -> None:
    if user.get("role") != "teacher":
        return
    from services import teacher_service

    teacher = await teacher_service.get_teacher_by_user_id(user["school_id"], user["id"])
    if teacher.is_class_teacher:
        ct_class = (teacher.class_teacher_class_name or "").strip().lower()
        ct_section = (teacher.class_teacher_section_name or "").strip().lower()
        if ct_class == (class_name or "").strip().lower() and (
            not section_name
            or ct_section == (section_name or "").strip().lower()
        ):
            return
    if _teacher_teaches_class_section(
        teacher.classes_teaching or [], class_name, section_name
    ):
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN,
        "You can only view attendance for classes you teach",
    )


async def class_section_attendance_report(
    user: dict,
    *,
    class_name: str,
    section_name: str,
    days: int = 1,
) -> dict:
    school_id = user["school_id"]
    await assert_can_view_class_section(user, class_name, section_name)
    class_id, section_id = await _resolve_class_section_ids(
        school_id, class_name, section_name
    )

    students = await student_service.list_students(school_id, class_id, section_id)
    total_students = len(students)
    emails = [student.email for student in students if student.email]

    today = date.today()
    start = today - timedelta(days=days - 1)
    present_by_date: Dict[str, int] = defaultdict(int)

    if emails:
        client = get_client()
        res = (
            await client.table("attendance")
            .select("date, status, student_email")
            .eq("school_id", school_id)
            .gte("date", start.isoformat())
            .lte("date", today.isoformat())
            .in_("student_email", emails)
            .execute()
        )
        for row in res.data or []:
            if row.get("status") == "present":
                present_by_date[row["date"]] += 1

    points = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        key = d.isoformat()
        points.append(
            {
                "date": key,
                "present": present_by_date.get(key, 0),
                "label": str(d.day),
            }
        )

    payload: dict = {
        "points": points,
        "days": days,
        "class_name": class_name,
        "section_name": section_name,
    }
    if days == 1:
        present = points[-1]["present"] if points else 0
        leave_count = 0
        if emails:
            client = get_client()
            leave_res = (
                await client.table("attendance")
                .select("student_email")
                .eq("school_id", school_id)
                .eq("date", today.isoformat())
                .eq("status", "leave")
                .in_("student_email", emails)
                .execute()
            )
            leave_count = len(leave_res.data or [])
        absent = max(total_students - present - leave_count, 0)
        pct = round((present / total_students) * 100) if total_students else 0
        payload["summary"] = {
            "total": total_students,
            "present": present,
            "absent": absent,
            "pct": pct,
        }
    return payload
