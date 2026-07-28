"""Announcements (scoped per school)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel

from database import get_client
from schemas.content import (
    Announcement,
    AnnouncementAttachmentOut,
    AnnouncementAudienceTargets,
    AnnouncementRecipientItem,
)
from services import announcement_service
from services.announcement_attachment_service import (
    delete_announcement_attachment,
    resolve_announcement_attachment,
    save_announcement_attachment,
)
from services.notification_service import notify_school
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/announcements", tags=["announcements"])

_COLUMNS = (
    "id,school_id,title,body,audience,author,"
    "attachment_url,attachment_name,recipient_user_id,recipient_name,recipient_type,recipients,"
    "audience_targets,created_at"
)
_CREATE_ROLES = ("school_admin", "principal", "vice_principal", "super_admin")
_MANAGE_ROLES = ("school_admin", "principal", "vice_principal", "super_admin")


class AnnouncementRecipientOut(BaseModel):
    user_id: str
    full_name: str
    admission_no: Optional[str] = None


class AnnouncementRecipientsOut(BaseModel):
    teachers: List[AnnouncementRecipientOut]
    students: List[AnnouncementRecipientOut]


async def _student_recipients(school_id: str) -> List[AnnouncementRecipientOut]:
    client = get_client()
    res = (
        await client.table("students")
        .select("user_id,admission_no")
        .eq("school_id", school_id)
        .execute()
    )
    rows = res.data or []
    user_ids = [row["user_id"] for row in rows if row.get("user_id")]
    if not user_ids:
        return []

    users_res = (
        await client.table("users")
        .select("id,full_name,admission_no")
        .in_("id", user_ids)
        .execute()
    )
    users_by_id = {row["id"]: row for row in (users_res.data or [])}
    recipients: List[AnnouncementRecipientOut] = []
    for row in rows:
        user_id = row.get("user_id")
        if not user_id:
            continue
        user = users_by_id.get(user_id, {})
        admission_no = (row.get("admission_no") or user.get("admission_no") or "").strip() or None
        recipients.append(
            AnnouncementRecipientOut(
                user_id=user_id,
                full_name=user.get("full_name") or "Student",
                admission_no=admission_no,
            )
        )
    recipients.sort(key=lambda item: (item.admission_no or "", item.full_name.lower()))
    return recipients


async def _teacher_recipients(school_id: str) -> List[AnnouncementRecipientOut]:
    client = get_client()
    res = await client.table("teachers").select("user_id").eq("school_id", school_id).execute()
    rows = res.data or []
    user_ids = [row["user_id"] for row in rows if row.get("user_id")]
    if not user_ids:
        return []

    users_res = (
        await client.table("users")
        .select("id,full_name")
        .in_("id", user_ids)
        .execute()
    )
    names = {row["id"]: row.get("full_name") or "Teacher" for row in (users_res.data or [])}
    recipients = [
        AnnouncementRecipientOut(user_id=row["user_id"], full_name=names.get(row["user_id"], "Teacher"))
        for row in rows
        if row.get("user_id")
    ]
    recipients.sort(key=lambda item: item.full_name.lower())
    return recipients


@router.get("/recipients", response_model=AnnouncementRecipientsOut)
async def list_announcement_recipients(
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> AnnouncementRecipientsOut:
    teachers = await _teacher_recipients(user["school_id"])
    students = await _student_recipients(user["school_id"])
    return AnnouncementRecipientsOut(teachers=teachers, students=students)


@router.get("/for-me", response_model=List[Announcement])
async def list_my_announcements(
    limit: int = Query(5, ge=1, le=20),
    user: dict = Depends(current_user),
) -> List[Announcement]:
    return await announcement_service.list_announcements_for_user(
        user["school_id"],
        user,
        limit=limit,
    )


@router.get("", response_model=List[Announcement])
async def list_announcements(
    audience: str | None = None,
    month: int | None = None,
    year: int | None = None,
    date: str | None = None,
    user: dict = Depends(current_user),
) -> List[Announcement]:
    return await announcement_service.list_announcements(
        user["school_id"],
        audience=audience,
        month=month,
        year=year,
        on_date=date,
    )


@router.post("/upload-attachment", response_model=AnnouncementAttachmentOut)
async def upload_announcement_attachment(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> AnnouncementAttachmentOut:
    saved = await save_announcement_attachment(user["school_id"], file)
    return AnnouncementAttachmentOut(
        attachment_url=saved["attachment_url"],
        attachment_name=saved["attachment_name"],
    )


@router.delete("/attachments/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement_attachment_file(
    filename: str,
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> Response:
    delete_announcement_attachment(user["school_id"], filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/attachments/{filename}")
async def get_announcement_attachment(
    filename: str,
    user: dict = Depends(current_user),
) -> FileResponse:
    path, mime = resolve_announcement_attachment(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)


@router.post("", response_model=Announcement)
async def create_announcement(
    body: Announcement,
    user: dict = Depends(require_roles(*_CREATE_ROLES)),
) -> Announcement:
    await announcement_service.purge_expired_announcements(user["school_id"])
    recipients = _validate_specific_recipients(body)
    targets = _validate_class_targets(body)
    client = get_client()
    row = {
        "school_id": user["school_id"],
        "author": user["full_name"],
        **_announcement_row(body, user, recipients, targets),
    }
    inserted = await client.table("announcements").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create announcement")
    created = Announcement(**inserted.data[0])
    await notify_school(
        user["school_id"], f"New announcement: {created.title}", created.body
    )
    return created


def _validate_specific_recipients(body: Announcement) -> List[AnnouncementRecipientItem]:
    recipients: List[AnnouncementRecipientItem] = list(body.recipients or [])
    if body.audience == "specific":
        if not recipients and body.recipient_user_id and body.recipient_name:
            recipients = [
                AnnouncementRecipientItem(
                    user_id=body.recipient_user_id,
                    full_name=body.recipient_name,
                )
            ]
        if not recipients or not body.recipient_type:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Specific announcements require at least one recipient",
            )
        if body.recipient_type not in ("teacher", "student"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid recipient type")
    return recipients


def _validate_class_targets(body: Announcement) -> AnnouncementAudienceTargets:
    if body.audience != "class":
        return AnnouncementAudienceTargets()
    targets = body.audience_targets or AnnouncementAudienceTargets()
    class_ids = [str(x) for x in (targets.class_ids or []) if x]
    if not class_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Class announcements require at least one class",
        )
    section_ids = [str(x) for x in (targets.section_ids or []) if x]
    # Multiple classes → all sections of those classes
    if len(class_ids) > 1:
        return AnnouncementAudienceTargets(
            class_ids=class_ids,
            section_ids=[],
            all_sections=True,
            class_names=list(targets.class_names or []),
            section_names=[],
        )
    all_sections = bool(targets.all_sections) or not section_ids
    return AnnouncementAudienceTargets(
        class_ids=class_ids,
        section_ids=[] if all_sections else section_ids,
        all_sections=all_sections,
        class_names=list(targets.class_names or []),
        section_names=[] if all_sections else list(targets.section_names or []),
    )


def _announcement_row(
    body: Announcement,
    user: dict,
    recipients: List[AnnouncementRecipientItem],
    targets: AnnouncementAudienceTargets,
) -> dict:
    primary = recipients[0] if recipients else None
    return {
        "title": body.title,
        "body": body.body,
        "audience": body.audience,
        "attachment_url": body.attachment_url,
        "attachment_name": body.attachment_name,
        "recipient_user_id": primary.user_id if body.audience == "specific" and primary else None,
        "recipient_name": primary.full_name if body.audience == "specific" and primary else None,
        "recipient_type": body.recipient_type if body.audience == "specific" else None,
        "recipients": [item.model_dump() for item in recipients] if body.audience == "specific" else [],
        "audience_targets": targets.model_dump() if body.audience == "class" else {},
    }


@router.put("/{announcement_id}", response_model=Announcement)
async def update_announcement(
    announcement_id: str,
    body: Announcement,
    user: dict = Depends(require_roles(*_MANAGE_ROLES)),
) -> Announcement:
    recipients = _validate_specific_recipients(body)
    targets = _validate_class_targets(body)
    client = get_client()
    existing = (
        await client.table("announcements")
        .select("id")
        .eq("school_id", user["school_id"])
        .eq("id", announcement_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found")

    updated = (
        await client.table("announcements")
        .update(_announcement_row(body, user, recipients, targets))
        .eq("school_id", user["school_id"])
        .eq("id", announcement_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update announcement")
    return Announcement(**updated.data[0])


@router.delete("/{announcement_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_announcement(
    announcement_id: str,
    user: dict = Depends(require_roles(*_MANAGE_ROLES)),
) -> Response:
    client = get_client()
    res = (
        await client.table("announcements")
        .delete()
        .eq("school_id", user["school_id"])
        .eq("id", announcement_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Announcement not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
