"""Substitute class assignments for teachers during free periods."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status

from database import get_client
from schemas.content import TeacherScheduleOut, TeacherSubstituteAssignIn
from services.schedule_days import is_valid_schedule_day
from services.teacher_schedule_service import get_teacher_schedule


async def _subject_name_for_period(
    client,
    school_id: str,
    section_id: str,
    period_index: int,
    day_of_week: str,
) -> str:
    res = (
        await client.table("class_section_period_assignments")
        .select("subject_name")
        .eq("school_id", school_id)
        .eq("section_id", section_id)
        .eq("period_index", period_index)
        .eq("day_of_week", day_of_week)
        .limit(1)
        .execute()
    )
    if not res.data:
        return ""
    return res.data[0].get("subject_name") or ""


async def assign_substitute(
    school_id: str,
    body: TeacherSubstituteAssignIn,
) -> TeacherScheduleOut:
    client = get_client()

    if not is_valid_schedule_day(body.day_of_week):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid day of week")

    teacher_res = (
        await client.table("teachers")
        .select("id")
        .eq("school_id", school_id)
        .eq("id", body.teacher_id)
        .limit(1)
        .execute()
    )
    if not teacher_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")

    class_res = (
        await client.table("classes")
        .select("id")
        .eq("school_id", school_id)
        .eq("id", body.class_id)
        .limit(1)
        .execute()
    )
    if not class_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")

    section_res = (
        await client.table("sections")
        .select("id")
        .eq("class_id", body.class_id)
        .eq("id", body.section_id)
        .limit(1)
        .execute()
    )
    if not section_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")

    regular_res = (
        await client.table("class_section_period_assignments")
        .select("id")
        .eq("school_id", school_id)
        .eq("teacher_id", body.teacher_id)
        .eq("period_index", body.period_index)
        .eq("day_of_week", body.day_of_week)
        .limit(1)
        .execute()
    )
    if regular_res.data:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Teacher already has a class during this period",
        )

    subject_name = await _subject_name_for_period(
        client,
        school_id,
        body.section_id,
        body.period_index,
        body.day_of_week,
    )

    now = datetime.now(timezone.utc).isoformat()
    inserted = (
        await client.table("teacher_substitute_assignments")
        .upsert(
            {
                "school_id": school_id,
                "teacher_id": body.teacher_id,
                "class_id": body.class_id,
                "section_id": body.section_id,
                "period_index": body.period_index,
                "day_of_week": body.day_of_week,
                "subject_name": subject_name,
                "created_at": now,
            },
            on_conflict="teacher_id,period_index,day_of_week",
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to assign substitute")

    return await get_teacher_schedule(school_id, body.teacher_id)
