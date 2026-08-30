"""Study material folders and files (scoped per school, per subject)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.study_material import (
    StudyFileOut,
    StudyFileUploadOut,
    StudyFolderCreateIn,
    StudyFolderOut,
)

_FOLDER_COLUMNS = (
    "id,school_id,subject_id,subject_name,name,created_by,created_by_name,"
    "created_at,updated_at"
)
_FILE_COLUMNS = (
    "id,school_id,folder_id,file_name,file_url,content_type,file_size,"
    "uploaded_by,uploaded_by_name,created_at"
)

_TEACHER_ROLES = {"teacher", "school_admin", "principal", "vice_principal"}


def _can_manage(user: dict) -> bool:
    return user.get("role") in _TEACHER_ROLES


DEFAULT_FOLDERS = ["Notes", "Worksheets", "Recording", "Extras"]


async def list_folders(
    school_id: str,
    *,
    subject_id: Optional[str] = None,
    subject_name: Optional[str] = None,
) -> List[StudyFolderOut]:
    client = get_client()
    query = (
        client.table("study_folders")
        .select(_FOLDER_COLUMNS)
        .eq("school_id", school_id)
    )
    if subject_id:
        query = query.eq("subject_id", subject_id)
    elif subject_name:
        query = query.ilike("subject_name", subject_name.strip())
    folders_res = await query.order("name", desc=False).execute()

    # Fetch file counts + latest file per folder.
    file_res = (
        await client.table("study_files")
        .select("folder_id,file_name,created_at")
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .execute()
    )
    count_by_folder: dict[str, int] = {}
    latest_by_folder: dict[str, dict] = {}
    for row in file_res.data or []:
        fid = row["folder_id"]
        count_by_folder[fid] = count_by_folder.get(fid, 0) + 1
        if fid not in latest_by_folder:
            latest_by_folder[fid] = row

    # Build a map of existing folder names (lowercase) for this subject.
    existing_names: set[str] = set()
    db_rows: list[dict] = list(folders_res.data or [])
    for row in db_rows:
        existing_names.add((row.get("name") or "").strip().lower())

    # Merge: default folders first, then any custom folders from the DB.
    result: List[StudyFolderOut] = []

    # Default folders (virtual — not in DB unless a teacher created one with the same name).
    for name in DEFAULT_FOLDERS:
        # If a DB folder has the same name, use the DB row instead.
        match_row = None
        for row in db_rows:
            if (row.get("name") or "").strip().lower() == name.lower():
                match_row = row
                break
        if match_row:
            fid = match_row["id"]
            latest = latest_by_folder.get(fid)
            result.append(
                StudyFolderOut(
                    **match_row,
                    file_count=count_by_folder.get(fid, 0),
                    latest_file_name=latest["file_name"] if latest else None,
                    latest_file_at=latest["created_at"] if latest else None,
                )
            )
        else:
            # Virtual default folder — no DB record yet.
            result.append(
                StudyFolderOut(
                    id=f"default_{name.lower()}",
                    school_id=school_id,
                    subject_id=subject_id,
                    subject_name=(subject_name or "").strip(),
                    name=name,
                    created_by=None,
                    created_by_name="",
                    file_count=0,
                    latest_file_name=None,
                    latest_file_at=None,
                    created_at=None,
                    updated_at=None,
                )
            )

    # Custom folders from the DB (excluding defaults already added).
    for row in db_rows:
        name_lower = (row.get("name") or "").strip().lower()
        if name_lower in {n.lower() for n in DEFAULT_FOLDERS}:
            continue  # Already added above.
        fid = row["id"]
        latest = latest_by_folder.get(fid)
        result.append(
            StudyFolderOut(
                **row,
                file_count=count_by_folder.get(fid, 0),
                latest_file_name=latest["file_name"] if latest else None,
                latest_file_at=latest["created_at"] if latest else None,
            )
        )

    return result


async def create_folder(school_id: str, body: StudyFolderCreateIn, user: dict) -> StudyFolderOut:
    if not _can_manage(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers can create folders")
    name = body.name.strip()
    if not name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Folder name is required")
    client = get_client()
    # Check duplicate within same subject.
    dup_q = (
        client.table("study_folders")
        .select("id")
        .eq("school_id", school_id)
        .ilike("name", name)
    )
    if body.subject_id:
        dup_q = dup_q.eq("subject_id", body.subject_id)
    elif body.subject_name:
        dup_q = dup_q.ilike("subject_name", body.subject_name.strip())
    dup = await dup_q.limit(1).execute()
    if dup.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "A folder with this name already exists for this subject")

    row = {
        "school_id": school_id,
        "subject_id": body.subject_id,
        "subject_name": body.subject_name.strip(),
        "name": name,
        "created_by": user["id"],
        "created_by_name": user.get("full_name", ""),
    }
    inserted = await client.table("study_folders").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create folder")
    return StudyFolderOut(
        **inserted.data[0],
        file_count=0,
        latest_file_name=None,
        latest_file_at=None,
    )


async def delete_folder(school_id: str, folder_id: str, user: dict) -> None:
    if not _can_manage(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers can delete folders")
    client = get_client()
    # Verify ownership for teachers (admins can delete any).
    if user.get("role") == "teacher":
        res = (
            await client.table("study_folders")
            .select("created_by")
            .eq("school_id", school_id)
            .eq("id", folder_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
        if res.data[0].get("created_by") and res.data[0]["created_by"] != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete folders you created")
    await client.table("study_folders").delete().eq("school_id", school_id).eq("id", folder_id).execute()


async def list_files(school_id: str, folder_id: str) -> List[StudyFileOut]:
    client = get_client()
    res = (
        await client.table("study_files")
        .select(_FILE_COLUMNS)
        .eq("school_id", school_id)
        .eq("folder_id", folder_id)
        .order("created_at", desc=True)
        .execute()
    )
    return [StudyFileOut(**row) for row in (res.data or [])]


async def add_file_record(
    school_id: str,
    folder_id: str,
    upload: dict,
    user: dict,
) -> StudyFileOut:
    if not _can_manage(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers can upload files")
    client = get_client()
    # Verify folder exists.
    folder_res = (
        await client.table("study_folders")
        .select("id,created_by")
        .eq("school_id", school_id)
        .eq("id", folder_id)
        .limit(1)
        .execute()
    )
    if not folder_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Folder not found")
    if user.get("role") == "teacher":
        owner = folder_res.data[0].get("created_by")
        if owner and owner != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only upload to folders you created")

    row = {
        "school_id": school_id,
        "folder_id": folder_id,
        "file_name": upload["file_name"],
        "file_url": upload["file_url"],
        "content_type": upload.get("content_type", "application/octet-stream"),
        "file_size": upload.get("file_size", 0),
        "uploaded_by": user["id"],
        "uploaded_by_name": user.get("full_name", ""),
    }
    inserted = await client.table("study_files").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save file record")
    # Touch folder updated_at.
    await client.table("study_folders").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", folder_id).execute()
    return StudyFileOut(**inserted.data[0])


async def delete_file(school_id: str, file_id: str, user: dict) -> None:
    if not _can_manage(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only teachers can delete files")
    client = get_client()
    res = (
        await client.table("study_files")
        .select("id,file_url,uploaded_by")
        .eq("school_id", school_id)
        .eq("id", file_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File not found")
    if user.get("role") == "teacher":
        owner = res.data[0].get("uploaded_by")
        if owner and owner != user["id"]:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete files you uploaded")
    await client.table("study_files").delete().eq("school_id", school_id).eq("id", file_id).execute()
