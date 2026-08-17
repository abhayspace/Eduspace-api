"""Class syllabus routes: syllabus per class-section, terms, and chapters."""
from typing import List

from fastapi import APIRouter, Depends, Response, status

from schemas.syllabus import (
    SyllabusChapterIn,
    SyllabusChapterOut,
    SyllabusChapterStatusIn,
    SyllabusCreateIn,
    SyllabusOut,
    SyllabusTermIn,
    SyllabusTermOut,
)
from services import syllabus_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/syllabus", tags=["syllabus"])

# Everyone in the school can read the syllabus; only staff can change it.
staff_only = require_roles("teacher", "school_admin", "principal", "vice_principal")


@router.get("", response_model=List[SyllabusOut])
async def list_syllabi(user: dict = Depends(current_user)) -> List[SyllabusOut]:
    return await syllabus_service.list_syllabi(user["school_id"])


@router.get("/{syllabus_id}", response_model=SyllabusOut)
async def get_syllabus(syllabus_id: str, user: dict = Depends(current_user)) -> SyllabusOut:
    return await syllabus_service.get_syllabus(user["school_id"], syllabus_id)


@router.post("", response_model=SyllabusOut, status_code=status.HTTP_201_CREATED)
async def create_syllabus(
    body: SyllabusCreateIn,
    user: dict = Depends(staff_only),
) -> SyllabusOut:
    return await syllabus_service.create_syllabus(user["school_id"], user["id"], body)


@router.delete("/{syllabus_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_syllabus(syllabus_id: str, user: dict = Depends(staff_only)) -> Response:
    await syllabus_service.delete_syllabus(user["school_id"], syllabus_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{syllabus_id}/terms",
    response_model=SyllabusTermOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_term(
    syllabus_id: str,
    body: SyllabusTermIn,
    user: dict = Depends(staff_only),
) -> SyllabusTermOut:
    return await syllabus_service.add_term(user["school_id"], syllabus_id, body)


@router.put("/terms/{term_id}", response_model=SyllabusTermOut)
async def rename_term(
    term_id: str,
    body: SyllabusTermIn,
    user: dict = Depends(staff_only),
) -> SyllabusTermOut:
    return await syllabus_service.rename_term(user["school_id"], term_id, body)


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_term(term_id: str, user: dict = Depends(staff_only)) -> Response:
    await syllabus_service.delete_term(user["school_id"], term_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/terms/{term_id}/chapters",
    response_model=SyllabusChapterOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_chapter(
    term_id: str,
    body: SyllabusChapterIn,
    user: dict = Depends(staff_only),
) -> SyllabusChapterOut:
    return await syllabus_service.add_chapter(user["school_id"], term_id, body)


@router.put("/chapters/{chapter_id}", response_model=SyllabusChapterOut)
async def update_chapter(
    chapter_id: str,
    body: SyllabusChapterIn,
    user: dict = Depends(staff_only),
) -> SyllabusChapterOut:
    return await syllabus_service.update_chapter(user["school_id"], chapter_id, body)


@router.put("/chapters/{chapter_id}/status", response_model=SyllabusChapterOut)
async def set_chapter_completed(
    chapter_id: str,
    body: SyllabusChapterStatusIn,
    user: dict = Depends(staff_only),
) -> SyllabusChapterOut:
    return await syllabus_service.set_chapter_completed(user["school_id"], chapter_id, body)


@router.delete("/chapters/{chapter_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chapter(chapter_id: str, user: dict = Depends(staff_only)) -> Response:
    await syllabus_service.delete_chapter(user["school_id"], chapter_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
