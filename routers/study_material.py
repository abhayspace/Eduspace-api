"""Study material folders and files router."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import FileResponse

from schemas.study_material import (
    StudyFileOut,
    StudyFileUploadOut,
    StudyFolderCreateIn,
    StudyFolderOut,
)
from services import study_material_service
from services.study_material_storage_service import (
    delete_study_file,
    resolve_study_file,
    save_study_file,
)
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/study-material", tags=["study-material"])

_MANAGE_ROLES = ("teacher", "school_admin", "principal", "vice_principal")


@router.get("/folders", response_model=List[StudyFolderOut])
async def list_folders(
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
    user: dict = Depends(current_user),
) -> List[StudyFolderOut]:
    return await study_material_service.list_folders(
        user["school_id"],
        subject_id=subject_id,
        subject_name=subject_name,
    )


@router.post("/folders", response_model=StudyFolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: StudyFolderCreateIn,
    user: dict = Depends(require_roles(*_MANAGE_ROLES)),
) -> StudyFolderOut:
    return await study_material_service.create_folder(user["school_id"], body, user)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    user: dict = Depends(require_roles(*_MANAGE_ROLES)),
) -> Response:
    await study_material_service.delete_folder(user["school_id"], folder_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/folders/{folder_id}/files", response_model=List[StudyFileOut])
async def list_files(
    folder_id: str,
    user: dict = Depends(current_user),
) -> List[StudyFileOut]:
    return await study_material_service.list_files(user["school_id"], folder_id)


@router.post("/folders/{folder_id}/upload", response_model=StudyFileOut, status_code=status.HTTP_201_CREATED)
async def upload_file(
    folder_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_roles(*_MANAGE_ROLES)),
) -> StudyFileOut:
    saved = await save_study_file(user["school_id"], file)
    return await study_material_service.add_file_record(user["school_id"], folder_id, saved, user)


@router.delete("/files/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_file(
    file_id: str,
    user: dict = Depends(require_roles(*_MANAGE_ROLES)),
) -> Response:
    await study_material_service.delete_file(user["school_id"], file_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files/{filename}")
async def get_file(
    filename: str,
    user: dict = Depends(current_user),
) -> FileResponse:
    path, mime = resolve_study_file(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)
