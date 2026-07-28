"""School timing and period timetables."""
from typing import List, Optional

from fastapi import APIRouter, Depends

from schemas.content import (
    ClassSectionScheduleOut,
    ClassSectionScheduleUpsertIn,
    PeriodTimetableCreateIn,
    PeriodTimetableOut,
    PeriodTimetableUpdateIn,
    SchoolTimingOut,
    SchoolTimingUpsertIn,
    TeacherScheduleOut,
    TeacherSubstituteAssignIn,
)
from schemas.people import TeacherBriefOut
from services import class_section_schedule_service, schedule_timing_service, teacher_schedule_service
from services import teacher_substitute_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/schedule", tags=["schedule"])

_SCHEDULE_WRITE_ROLES = (
    "school_admin",
    "principal",
    "vice_principal",
    "super_admin",
)


@router.get("/school-timing", response_model=Optional[SchoolTimingOut])
async def get_school_timing(user: dict = Depends(current_user)) -> Optional[SchoolTimingOut]:
    return await schedule_timing_service.get_school_timing(user["school_id"])


@router.put("/school-timing", response_model=SchoolTimingOut)
async def upsert_school_timing(
    body: SchoolTimingUpsertIn,
    user: dict = Depends(require_roles(*_SCHEDULE_WRITE_ROLES)),
) -> SchoolTimingOut:
    return await schedule_timing_service.upsert_school_timing(user["school_id"], body)


@router.get("/period-timetables", response_model=List[PeriodTimetableOut])
async def list_period_timetables(
    user: dict = Depends(current_user),
) -> List[PeriodTimetableOut]:
    return await schedule_timing_service.list_period_timetables(user["school_id"])


@router.post("/period-timetables", response_model=PeriodTimetableOut)
async def create_period_timetable(
    body: PeriodTimetableCreateIn,
    user: dict = Depends(require_roles(*_SCHEDULE_WRITE_ROLES)),
) -> PeriodTimetableOut:
    return await schedule_timing_service.create_period_timetable(user["school_id"], body)


@router.put("/period-timetables/{timetable_id}", response_model=PeriodTimetableOut)
async def update_period_timetable(
    timetable_id: str,
    body: PeriodTimetableUpdateIn,
    user: dict = Depends(require_roles(*_SCHEDULE_WRITE_ROLES)),
) -> PeriodTimetableOut:
    return await schedule_timing_service.update_period_timetable(
        user["school_id"],
        timetable_id,
        body,
    )


@router.delete("/period-timetables/{timetable_id}", status_code=204)
async def delete_period_timetable(
    timetable_id: str,
    user: dict = Depends(require_roles(*_SCHEDULE_WRITE_ROLES)),
) -> None:
    await schedule_timing_service.delete_period_timetable(user["school_id"], timetable_id)


@router.get("/class-section-schedule", response_model=ClassSectionScheduleOut)
async def get_class_section_schedule(
    class_id: str,
    section_id: str,
    day_of_week: str = "monday",
    user: dict = Depends(current_user),
) -> ClassSectionScheduleOut:
    return await class_section_schedule_service.get_class_section_schedule(
        user["school_id"],
        class_id,
        section_id,
        day_of_week,
    )


@router.put("/class-section-schedule", response_model=ClassSectionScheduleOut)
async def upsert_class_section_schedule(
    body: ClassSectionScheduleUpsertIn,
    user: dict = Depends(require_roles(*_SCHEDULE_WRITE_ROLES)),
) -> ClassSectionScheduleOut:
    return await class_section_schedule_service.upsert_class_section_schedule(
        user["school_id"],
        body,
    )


@router.get("/subject-teachers", response_model=List[TeacherBriefOut])
async def list_subject_teachers(
    subject_id: str,
    user: dict = Depends(current_user),
) -> List[TeacherBriefOut]:
    return await class_section_schedule_service.list_teachers_for_subject(
        user["school_id"],
        subject_id,
    )


@router.get("/teacher-schedule/{teacher_id}", response_model=TeacherScheduleOut)
async def get_teacher_schedule(
    teacher_id: str,
    user: dict = Depends(current_user),
) -> TeacherScheduleOut:
    return await teacher_schedule_service.get_teacher_schedule(user["school_id"], teacher_id)


@router.post("/teacher-substitute", response_model=TeacherScheduleOut)
async def assign_teacher_substitute(
    body: TeacherSubstituteAssignIn,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal", "super_admin")),
) -> TeacherScheduleOut:
    return await teacher_substitute_service.assign_substitute(user["school_id"], body)
