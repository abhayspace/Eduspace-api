"""Academic structure — classes, sections, subjects."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Response, status

from schemas.people import (
    ClassCreateIn,
    ClassOut,
    ClassTeacherAssignIn,
    SectionOut,
    SectionUpdateIn,
    SubjectOut,
    TeacherBriefOut,
    TeacherOut,
)
from services import academic_service
from services import teacher_service
from utils.deps import current_user

router = APIRouter(prefix="/academic", tags=["academic"])


@router.get("/classes", response_model=List[ClassOut])
async def list_classes(user: dict = Depends(current_user)) -> List[ClassOut]:
    return await academic_service.list_classes(user["school_id"])


@router.post("/classes", response_model=ClassOut)
async def create_class(payload: ClassCreateIn, user: dict = Depends(current_user)) -> ClassOut:
    return await academic_service.create_class(user["school_id"], payload.name, payload.sections)


@router.delete("/classes/{class_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_class(class_id: str, user: dict = Depends(current_user)) -> Response:
    await academic_service.delete_class(user["school_id"], class_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/sections/{section_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_section(section_id: str, user: dict = Depends(current_user)) -> Response:
    await academic_service.delete_section(user["school_id"], section_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/sections/{section_id}", response_model=SectionOut)
async def update_section(
    section_id: str,
    payload: SectionUpdateIn,
    user: dict = Depends(current_user),
) -> SectionOut:
    return await academic_service.update_section(user["school_id"], section_id, payload.name)


@router.get("/sections", response_model=List[SectionOut])
async def list_sections(
    class_id: Optional[str] = None,
    user: dict = Depends(current_user),
) -> List[SectionOut]:
    return await academic_service.list_sections(user["school_id"], class_id)


@router.get("/subjects", response_model=List[SubjectOut])
async def list_subjects(user: dict = Depends(current_user)) -> List[SubjectOut]:
    return await academic_service.list_subjects(user["school_id"])


@router.get("/teachers", response_model=List[TeacherBriefOut])
async def list_teachers_for_assign(user: dict = Depends(current_user)) -> List[TeacherBriefOut]:
    return await academic_service.list_teachers_brief(user["school_id"])


@router.post("/assign-class-teacher", response_model=TeacherOut)
async def assign_class_teacher(
    payload: ClassTeacherAssignIn,
    user: dict = Depends(current_user),
) -> TeacherOut:
    return await academic_service.assign_class_teacher(
        user["school_id"],
        payload.teacher_id,
        payload.class_id,
        payload.section_id,
    )
