"""Class-section period subject and teacher assignments."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.content import (
    ClassSectionPeriodAssignmentIn,
    ClassSectionPeriodOut,
    ClassSectionScheduleOut,
    ClassSectionScheduleUpsertIn,
)
from schemas.people import TeacherBriefOut
from services.schedule_days import is_valid_schedule_day


async def _class_name(client, school_id: str, class_id: str) -> str:
    res = (
        await client.table("classes")
        .select("name")
        .eq("id", class_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    return res.data[0].get("name") or "Class"


async def _section_name(client, class_id: str, section_id: str) -> str:
    res = (
        await client.table("sections")
        .select("name")
        .eq("id", section_id)
        .eq("class_id", class_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    return res.data[0].get("name") or "Section"


async def _period_slots_for_class(client, class_id: str) -> List[dict]:
    link = (
        await client.table("period_timetable_classes")
        .select("timetable_id")
        .eq("class_id", class_id)
        .limit(1)
        .execute()
    )
    if not link.data:
        return []

    timetable_id = link.data[0]["timetable_id"]
    header = (
        await client.table("period_timetables")
        .select("period_count,times_saved")
        .eq("id", timetable_id)
        .limit(1)
        .execute()
    )
    if not header.data:
        return []

    row = header.data[0]
    period_count = row["period_count"]
    slots_res = (
        await client.table("period_timetable_slots")
        .select("period_index,start_time,start_meridiem,end_time,end_meridiem")
        .eq("timetable_id", timetable_id)
        .order("period_index")
        .execute()
    )
    by_index = {slot["period_index"]: slot for slot in (slots_res.data or [])}
    return [
        {
            "period_index": index,
            "start_time": by_index.get(index, {}).get("start_time") or "",
            "start_meridiem": by_index.get(index, {}).get("start_meridiem") or "AM",
            "end_time": by_index.get(index, {}).get("end_time") or "",
            "end_meridiem": by_index.get(index, {}).get("end_meridiem") or "AM",
        }
        for index in range(period_count)
    ]


async def _assignments_for_section(
    client,
    school_id: str,
    section_id: str,
    day_of_week: str,
) -> Dict[int, dict]:
    res = (
        await client.table("class_section_period_assignments")
        .select(
            "period_index,subject_id,subject_name,teacher_id,teacher_name"
        )
        .eq("school_id", school_id)
        .eq("section_id", section_id)
        .eq("day_of_week", day_of_week)
        .execute()
    )
    return {row["period_index"]: row for row in (res.data or [])}


async def _subject_name(client, school_id: str, subject_id: str) -> str:
    res = (
        await client.table("subjects")
        .select("name")
        .eq("id", subject_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid subject")
    return res.data[0].get("name") or ""


async def _teacher_name(client, school_id: str, teacher_id: str) -> str:
    res = (
        await client.table("teachers")
        .select("user_id")
        .eq("id", teacher_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid teacher")
    user_id = res.data[0].get("user_id")
    if not user_id:
        return "Teacher"
    user = (
        await client.table("users")
        .select("full_name")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    return (user.data or [{}])[0].get("full_name") or "Teacher"


async def _teacher_teaches_subject(
    client,
    school_id: str,
    teacher_id: str,
    subject_name: str,
) -> bool:
    res = (
        await client.table("teachers")
        .select("subjects")
        .eq("id", teacher_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return False
    subjects = res.data[0].get("subjects") or []
    target = subject_name.strip().lower()
    return any(str(item).strip().lower() == target for item in subjects)


def _normalize_day(day_of_week: str) -> str:
    day = (day_of_week or "").strip().lower()
    if not is_valid_schedule_day(day):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid day of week")
    return day


async def get_class_section_schedule(
    school_id: str,
    class_id: str,
    section_id: str,
    day_of_week: str = "monday",
) -> ClassSectionScheduleOut:
    client = get_client()
    day = _normalize_day(day_of_week)
    class_name = await _class_name(client, school_id, class_id)
    section_name = await _section_name(client, class_id, section_id)

    slots = await _period_slots_for_class(client, class_id)
    assignments = await _assignments_for_section(client, school_id, section_id, day)

    periods: List[ClassSectionPeriodOut] = []
    for slot in slots:
        index = slot["period_index"]
        assignment = assignments.get(index, {})
        periods.append(
            ClassSectionPeriodOut(
                period_index=index,
                start_time=slot.get("start_time") or "",
                start_meridiem=slot.get("start_meridiem") or "AM",
                end_time=slot.get("end_time") or "",
                end_meridiem=slot.get("end_meridiem") or "AM",
                subject_id=assignment.get("subject_id"),
                subject_name=assignment.get("subject_name") or "",
                teacher_id=assignment.get("teacher_id"),
                teacher_name=assignment.get("teacher_name") or "",
            )
        )

    return ClassSectionScheduleOut(
        class_id=class_id,
        class_name=class_name,
        section_id=section_id,
        section_name=section_name,
        day_of_week=day,
        has_period_timetable=len(slots) > 0,
        periods=periods,
    )


async def upsert_class_section_schedule(
    school_id: str,
    body: ClassSectionScheduleUpsertIn,
) -> ClassSectionScheduleOut:
    client = get_client()
    day = _normalize_day(body.day_of_week)
    await _class_name(client, school_id, body.class_id)
    await _section_name(client, body.class_id, body.section_id)

    slots = await _period_slots_for_class(client, body.class_id)
    if not slots:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Create period timing for this class first",
        )

    allowed_indexes = {slot["period_index"] for slot in slots}
    now = datetime.now(timezone.utc).isoformat()

    for item in body.assignments:
        if item.period_index not in allowed_indexes:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"Invalid period index {item.period_index}",
            )

        subject_name = ""
        teacher_name = ""
        subject_id = item.subject_id or None
        teacher_id = item.teacher_id or None

        if subject_id:
            subject_name = await _subject_name(client, school_id, subject_id)
        if teacher_id:
            if not subject_id:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    "Select a subject before assigning a teacher",
                )
            teacher_name = await _teacher_name(client, school_id, teacher_id)
            if subject_name and not await _teacher_teaches_subject(
                client, school_id, teacher_id, subject_name
            ):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"{teacher_name} does not teach {subject_name}",
                )

        if not subject_id and not teacher_id:
            await (
                client.table("class_section_period_assignments")
                .delete()
                .eq("school_id", school_id)
                .eq("section_id", body.section_id)
                .eq("period_index", item.period_index)
                .eq("day_of_week", day)
                .execute()
            )
            continue

        await (
            client.table("class_section_period_assignments")
            .upsert(
                {
                    "school_id": school_id,
                    "class_id": body.class_id,
                    "section_id": body.section_id,
                    "period_index": item.period_index,
                    "day_of_week": day,
                    "subject_id": subject_id,
                    "subject_name": subject_name,
                    "teacher_id": teacher_id,
                    "teacher_name": teacher_name,
                    "updated_at": now,
                },
                on_conflict="section_id,period_index,day_of_week",
            )
            .execute()
        )

    return await get_class_section_schedule(
        school_id,
        body.class_id,
        body.section_id,
        day,
    )


async def list_teachers_for_subject(school_id: str, subject_id: str) -> List[TeacherBriefOut]:
    client = get_client()
    subject_name = await _subject_name(client, school_id, subject_id)
    target = subject_name.strip().lower()

    teachers_res = (
        await client.table("teachers")
        .select("id,user_id,subjects")
        .eq("school_id", school_id)
        .execute()
    )
    rows = [
        row
        for row in (teachers_res.data or [])
        if any(str(item).strip().lower() == target for item in (row.get("subjects") or []))
    ]
    if not rows:
        return []

    user_ids = [row["user_id"] for row in rows if row.get("user_id")]
    users_res = await client.table("users").select("id,full_name").in_("id", user_ids).execute()
    names = {row["id"]: row.get("full_name") or "Teacher" for row in (users_res.data or [])}

    return [
        TeacherBriefOut(
            id=row["id"],
            full_name=names.get(row.get("user_id"), "Teacher"),
        )
        for row in rows
    ]
