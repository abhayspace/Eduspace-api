"""Gallery folders and media (scoped per school)."""
from __future__ import annotations

import asyncio
from typing import List

from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile, status

from database import get_client
from schemas.gallery import (
    GalleryFolderCreateIn,
    GalleryFolderOut,
    GalleryFolderUpdateIn,
    GalleryMediaOut,
)
from services.gallery_media_service import (
    delete_gallery_file,
    filename_from_file_url,
    save_gallery_media,
)

_FOLDER_COLUMNS = "id,school_id,name,created_at,updated_at"
_MEDIA_COLUMNS = "id,school_id,folder_id,media_type,file_url,file_name,content_type,created_at"


async def _folder_name_taken(school_id: str, name: str, exclude_id: str | None = None) -> bool:
    client = get_client()
    query = (
        client.table("gallery_folders")
        .select("id")
        .eq("school_id", school_id)
        .ilike("name", name.strip())
        .limit(1)
    )
    if exclude_id:
        query = query.neq("id", exclude_id)
    res = await query.execute()
    return bool(res.data)


async def _get_folder_row(school_id: str, folder_id: str) -> dict:
    client = get_client()
    res = (
        await client.table("gallery_folders")
        .select(_FOLDER_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", folder_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    return res.data[0]


async def list_folders(school_id: str) -> List[GalleryFolderOut]:
    client = get_client()
    folders_res, media_res = await asyncio.gather(
        client.table("gallery_folders")
        .select(_FOLDER_COLUMNS)
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .execute(),
        client.table("gallery_media")
        .select("folder_id,media_type,file_url,created_at")
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .execute(),
    )
    latest_by_folder: dict[str, dict] = {}
    for row in media_res.data or []:
        folder_id = row["folder_id"]
        if folder_id not in latest_by_folder:
            latest_by_folder[folder_id] = row

    folders: List[GalleryFolderOut] = []
    for row in folders_res.data or []:
        latest = latest_by_folder.get(row["id"])
        folders.append(
            GalleryFolderOut(
                **row,
                latest_media_type=latest["media_type"] if latest else None,
                latest_file_url=latest["file_url"] if latest else None,
            )
        )
    return folders


async def create_folder(school_id: str, body: GalleryFolderCreateIn) -> GalleryFolderOut:
    name = body.name.strip()
    if await _folder_name_taken(school_id, name):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A folder with this name already exists")
    client = get_client()
    inserted = (
        await client.table("gallery_folders")
        .insert({"school_id": school_id, "name": name})
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create folder")
    return GalleryFolderOut(**inserted.data[0])


async def update_folder(school_id: str, folder_id: str, body: GalleryFolderUpdateIn) -> GalleryFolderOut:
    await _get_folder_row(school_id, folder_id)
    name = body.name.strip()
    if await _folder_name_taken(school_id, name, folder_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A folder with this name already exists")
    client = get_client()
    updated = (
        await client.table("gallery_folders")
        .update({"name": name, "updated_at": datetime.now(timezone.utc).isoformat()})
        .eq("school_id", school_id)
        .eq("id", folder_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update folder")
    return GalleryFolderOut(**updated.data[0])


async def delete_folder(school_id: str, folder_id: str) -> None:
    await _get_folder_row(school_id, folder_id)
    media = await list_folder_media(school_id, folder_id)
    for item in media:
        try:
            delete_gallery_file(school_id, filename_from_file_url(item.file_url))
        except HTTPException:
            pass
    client = get_client()
    await client.table("gallery_folders").delete().eq("school_id", school_id).eq("id", folder_id).execute()


async def list_folder_media(school_id: str, folder_id: str) -> List[GalleryMediaOut]:
    await _get_folder_row(school_id, folder_id)
    client = get_client()
    res = (
        await client.table("gallery_media")
        .select(_MEDIA_COLUMNS)
        .eq("school_id", school_id)
        .eq("folder_id", folder_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [GalleryMediaOut(**row) for row in (res.data or [])]


async def upload_folder_media(school_id: str, folder_id: str, file: UploadFile) -> GalleryMediaOut:
    await _get_folder_row(school_id, folder_id)
    saved = await save_gallery_media(school_id, file)
    client = get_client()
    inserted = (
        await client.table("gallery_media")
        .insert(
            {
                "school_id": school_id,
                "folder_id": folder_id,
                "media_type": saved["media_type"],
                "file_url": saved["file_url"],
                "file_name": saved["file_name"],
                "content_type": saved["content_type"],
            }
        )
        .execute()
    )
    if not inserted.data:
        delete_gallery_file(school_id, saved["stored_name"])
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save media")
    return GalleryMediaOut(**inserted.data[0])


async def delete_media(school_id: str, media_id: str) -> None:
    client = get_client()
    res = (
        await client.table("gallery_media")
        .select(_MEDIA_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", media_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Media not found")
    row = res.data[0]
    try:
        delete_gallery_file(school_id, filename_from_file_url(row["file_url"]))
    except HTTPException:
        pass
    await client.table("gallery_media").delete().eq("school_id", school_id).eq("id", media_id).execute()
