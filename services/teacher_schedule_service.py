"""Teacher schedule — assigned classes and free periods."""
from __future__ import annotations

from typing import Dict, List, Set

from fastapi import HTTPException, status

from database import get_client
from schemas.content import (
    TeacherFreePeriodOut,
    TeacherScheduleDayOut,
    TeacherScheduleOut,
    TeacherScheduleSlotOut,
)
from services.class_section_schedule_service import (
    _class_name,
    _period_slots_for_class,
    _section_name,
)
from services.schedule_days import SCHOOL_DAYS


async def _school_period_template(client, school_id: str) -> List[dict]:
    res = (
        await client.table("period_timetables")
        .select("id,period_count")
        .eq("school_id", school_id)
        .eq("times_saved", True)
        .order("period_count", desc=True)
        .limit(1)
        .execute()
    )
    if not res.data:
        res = (
            await client.table("period_timetables")
            .select("id,period_count")
            .eq("school_id", school_id)
            .order("period_count", desc=True)
            .limit(1)
            .execute()
        )
    if not res.data:
        return []

    timetable_id = res.data[0]["id"]
    period_count = res.data[0]["period_count"]
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


def _slot_times(slots: List[dict], period_index: int) -> dict:
    match = next((slot for slot in slots if slot["period_index"] == period_index), None)
    if match:
        return match
    return {
        "period_index": period_index,
        "start_time": "",
        "start_meridiem": "AM",
        "end_time": "",
        "end_meridiem": "AM",
    }


def _free_periods_for_day(
    template: List[dict],
    busy_indexes: Set[int],
) -> List[TeacherFreePeriodOut]:
    return [
        TeacherFreePeriodOut(
            period_index=slot["period_index"],
            start_time=slot.get("start_time") or "",
            start_meridiem=slot.get("start_meridiem") or "AM",
            end_time=slot.get("end_time") or "",
            end_meridiem=slot.get("end_meridiem") or "AM",
        )
        for slot in template
        if slot["period_index"] not in busy_indexes
    ]


async def get_teacher_schedule(school_id: str, teacher_id: str) -> TeacherScheduleOut:
    client = get_client()
    teacher_res = (
        await client.table("teachers")
        .select("id,user_id,subjects")
        .eq("school_id", school_id)
        .eq("id", teacher_id)
        .limit(1)
        .execute()
    )
    if not teacher_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")

    profile = teacher_res.data[0]
    user_res = (
        await client.table("users")
        .select("full_name,user_code")
        .eq("id", profile["user_id"])
        .limit(1)
        .execute()
    )
    if not user_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher user not found")

    user = user_res.data[0]
    subjects = profile.get("subjects") or []

    assignments_res = (
        await client.table("class_section_period_assignments")
        .select("class_id,section_id,period_index,subject_name,day_of_week")
        .eq("school_id", school_id)
        .eq("teacher_id", teacher_id)
        .order("period_index")
        .execute()
    )
    assignments = assignments_res.data or []

    substitutes_res = (
        await client.table("teacher_substitute_assignments")
        .select("class_id,section_id,period_index,subject_name,day_of_week")
        .eq("school_id", school_id)
        .eq("teacher_id", teacher_id)
        .order("period_index")
        .execute()
    )
    substitutes = substitutes_res.data or []

    class_slots_cache: dict[str, List[dict]] = {}
    assignments_by_day: Dict[str, List[dict]] = {day: [] for day in SCHOOL_DAYS}
    for row in assignments:
        day = row.get("day_of_week") or "monday"
        if day not in assignments_by_day:
            assignments_by_day[day] = []
        assignments_by_day[day].append(row)

    substitutes_by_day: Dict[str, List[dict]] = {day: [] for day in SCHOOL_DAYS}
    for row in substitutes:
        day = row.get("day_of_week") or "monday"
        if day not in substitutes_by_day:
            substitutes_by_day[day] = []
        substitutes_by_day[day].append(row)

    template = await _school_period_template(client, school_id)
    days_out: List[TeacherScheduleDayOut] = []
    flat_class_slots: List[TeacherScheduleSlotOut] = []
    all_free_periods: Dict[int, TeacherFreePeriodOut] = {}

    for day in SCHOOL_DAYS:
        day_class_slots: List[TeacherScheduleSlotOut] = []
        busy_indexes: Set[int] = set()

        for row in assignments_by_day.get(day, []):
            class_id = row["class_id"]
            period_index = row["period_index"]
            if class_id not in class_slots_cache:
                class_slots_cache[class_id] = await _period_slots_for_class(client, class_id)
            times = _slot_times(class_slots_cache[class_id], period_index)
            class_name = await _class_name(client, school_id, class_id)
            section_name = await _section_name(client, class_id, row["section_id"])

            slot = TeacherScheduleSlotOut(
                period_index=period_index,
                start_time=times.get("start_time") or "",
                start_meridiem=times.get("start_meridiem") or "AM",
                end_time=times.get("end_time") or "",
                end_meridiem=times.get("end_meridiem") or "AM",
                class_name=class_name,
                section_name=section_name,
                subject_name=row.get("subject_name") or "",
                is_substitute=False,
                day_of_week=day,
            )
            day_class_slots.append(slot)
            flat_class_slots.append(slot)
            busy_indexes.add(period_index)

        for row in substitutes_by_day.get(day, []):
            class_id = row["class_id"]
            period_index = row["period_index"]
            if period_index in busy_indexes:
                continue
            if class_id not in class_slots_cache:
                class_slots_cache[class_id] = await _period_slots_for_class(client, class_id)
            times = _slot_times(class_slots_cache[class_id], period_index)
            class_name = await _class_name(client, school_id, class_id)
            section_name = await _section_name(client, class_id, row["section_id"])

            slot = TeacherScheduleSlotOut(
                period_index=period_index,
                start_time=times.get("start_time") or "",
                start_meridiem=times.get("start_meridiem") or "AM",
                end_time=times.get("end_time") or "",
                end_meridiem=times.get("end_meridiem") or "AM",
                class_name=class_name,
                section_name=section_name,
                subject_name=row.get("subject_name") or "",
                is_substitute=True,
                day_of_week=day,
            )
            day_class_slots.append(slot)
            flat_class_slots.append(slot)
            busy_indexes.add(period_index)

        day_class_slots.sort(
            key=lambda item: (item.period_index, item.class_name, item.section_name),
        )
        free_periods = _free_periods_for_day(template, busy_indexes)
        for slot in free_periods:
            all_free_periods.setdefault(slot.period_index, slot)

        days_out.append(
            TeacherScheduleDayOut(
                day_of_week=day,
                class_slots=day_class_slots,
                free_periods=free_periods,
            )
        )

    flat_class_slots.sort(
        key=lambda item: (
            item.day_of_week or "",
            item.period_index,
            item.class_name,
            item.section_name,
        ),
    )

    return TeacherScheduleOut(
        teacher_id=teacher_id,
        full_name=user.get("full_name") or "Teacher",
        user_code=user.get("user_code") or "",
        subjects=subjects,
        has_period_timetable=len(template) > 0,
        days=days_out,
        class_slots=flat_class_slots,
        free_periods=sorted(all_free_periods.values(), key=lambda item: item.period_index),
    )
