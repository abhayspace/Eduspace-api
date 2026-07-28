"""Homework assignments (scoped per school, rolling 1-year retention)."""
from typing import List

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import FileResponse

from schemas.content import HomeworkAttachmentOut, HomeworkItem
from services import homework_service
from services.homework_attachment_service import (
    delete_homework_attachment,
    resolve_homework_attachment,
    save_homework_attachment,
)
from services.notification_service import notify_school
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/homework", tags=["homework"])

_CREATE_ROLES = ("teacher", "principal", "school_admin")


@router.get("", response_model=List[HomeworkItem])
async def list_homework(user: dict = Depends(current_user)) -> List[HomeworkItem]:
    mine_only = user.get("role") == "teacher"
    return await homework_service.list_homework(
        user["school_id"],
        assigned_by_user_id=user["id"] if mine_only else None,
    )


@router.post("/upload-attachment", response_model=HomeworkAttachmentOut)
async def upload_homework_attachment(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> HomeworkAttachmentOut:
    saved = await save_homework_attachment(user["school_id"], file)
    return HomeworkAttachmentOut(
        attachment_url=saved["attachment_url"],
        attachment_name=saved["attachment_name"],
    )


@router.delete("/attachments/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_homework_attachment_file(
    filename: str,
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> Response:
    delete_homework_attachment(user["school_id"], filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/attachments/{filename}")
async def get_homework_attachment(
    filename: str,
    user: dict = Depends(current_user),
) -> FileResponse:
    path, mime = resolve_homework_attachment(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)


@router.post("", response_model=HomeworkItem)
async def create_homework(
    body: HomeworkItem,
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> HomeworkItem:
    await homework_service.assert_teacher_can_assign(
        user, body.class_name, body.section_name
    )
    created = await homework_service.create_homework(
        user["school_id"],
        subject=body.subject,
        title=body.title,
        description=body.description,
        class_name=body.class_name,
        section_name=body.section_name,
        due_date=body.due_date,
        assigned_by=user["full_name"],
        assigned_by_user_id=user["id"],
        attachment_url=body.attachment_url,
        attachment_name=body.attachment_name,
    )
    await notify_school(
        user["school_id"],
        f"New homework: {created.class_name}"
        + (f" {created.section_name}" if created.section_name else ""),
        f"{created.title} — due {created.due_date}",
    )
    return created


@router.put("/{homework_id}", response_model=HomeworkItem)
async def update_homework(
    homework_id: str,
    body: HomeworkItem,
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> HomeworkItem:
    row = await homework_service.get_homework(user["school_id"], homework_id)
    homework_service.assert_can_manage(user, row)
    await homework_service.assert_teacher_can_assign(
        user, body.class_name, body.section_name
    )
    return await homework_service.update_homework(
        user["school_id"],
        homework_id,
        subject=body.subject,
        title=body.title,
        description=body.description,
        class_name=body.class_name,
        section_name=body.section_name,
        due_date=body.due_date,
        attachment_url=body.attachment_url,
        attachment_name=body.attachment_name,
    )


@router.delete("/{homework_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_homework(
    homework_id: str,
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> Response:
    row = await homework_service.get_homework(user["school_id"], homework_id)
    homework_service.assert_can_manage(user, row)
    await homework_service.delete_homework(user["school_id"], homework_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
