"""Gallery folders and media (scoped per school)."""
from typing import List

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from fastapi.responses import FileResponse

from schemas.gallery import (
    GalleryFolderCreateIn,
    GalleryFolderOut,
    GalleryFolderUpdateIn,
    GalleryMediaOut,
)
from services import gallery_service
from services.gallery_media_service import resolve_gallery_file
from utils.deps import require_roles

router = APIRouter(prefix="/gallery", tags=["gallery"])

_GALLERY_VIEW_ROLES = ("school_admin", "principal", "vice_principal", "teacher")
_GALLERY_MANAGE_ROLES = ("school_admin", "principal", "vice_principal")


@router.get("/folders", response_model=List[GalleryFolderOut])
async def list_folders(
    user: dict = Depends(require_roles(*_GALLERY_VIEW_ROLES)),
) -> List[GalleryFolderOut]:
    return await gallery_service.list_folders(user["school_id"])


@router.post("/folders", response_model=GalleryFolderOut, status_code=status.HTTP_201_CREATED)
async def create_folder(
    body: GalleryFolderCreateIn,
    user: dict = Depends(require_roles(*_GALLERY_MANAGE_ROLES)),
) -> GalleryFolderOut:
    return await gallery_service.create_folder(user["school_id"], body)


@router.patch("/folders/{folder_id}", response_model=GalleryFolderOut)
async def update_folder(
    folder_id: str,
    body: GalleryFolderUpdateIn,
    user: dict = Depends(require_roles(*_GALLERY_MANAGE_ROLES)),
) -> GalleryFolderOut:
    return await gallery_service.update_folder(user["school_id"], folder_id, body)


@router.delete("/folders/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder(
    folder_id: str,
    user: dict = Depends(require_roles(*_GALLERY_MANAGE_ROLES)),
) -> Response:
    await gallery_service.delete_folder(user["school_id"], folder_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/folders/{folder_id}/media", response_model=List[GalleryMediaOut])
async def list_folder_media(
    folder_id: str,
    user: dict = Depends(require_roles(*_GALLERY_VIEW_ROLES)),
) -> List[GalleryMediaOut]:
    return await gallery_service.list_folder_media(user["school_id"], folder_id)


@router.post("/folders/{folder_id}/upload", response_model=GalleryMediaOut)
async def upload_folder_media(
    folder_id: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_roles(*_GALLERY_MANAGE_ROLES)),
) -> GalleryMediaOut:
    return await gallery_service.upload_folder_media(user["school_id"], folder_id, file)


@router.delete("/media/{media_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_media(
    media_id: str,
    user: dict = Depends(require_roles(*_GALLERY_MANAGE_ROLES)),
) -> Response:
    await gallery_service.delete_media(user["school_id"], media_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/files/{filename}")
async def get_gallery_file(
    filename: str,
    user: dict = Depends(require_roles(*_GALLERY_VIEW_ROLES)),
) -> FileResponse:
    path, mime = resolve_gallery_file(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)
