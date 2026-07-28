"""Homework assignments per school with rolling 1-year retention."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.content import HomeworkItem
from services.homework_attachment_service import (
    delete_homework_attachment,
    filename_from_attachment_url,
)

_COLUMNS = (
    "id,school_id,subject,title,description,class_name,section_name,"
    "due_date,assigned_by,assigned_by_user_id,attachment_url,attachment_name,created_at"
)
HOMEWORK_RETENTION_DAYS = 365


def retention_start(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=HOMEWORK_RETENTION_DAYS - 1)


def _cutoff_iso(today: date | None = None) -> str:
    return datetime.combine(
        retention_start(today or date.today()),
        time.min,
        tzinfo=timezone.utc,
    ).isoformat()


async def purge_expired_homework(school_id: str, today: date | None = None) -> None:
    cutoff = _cutoff_iso(today)
    client = get_client()
    expired = (
        await client.table("homework")
        .select("id,attachment_url")
        .eq("school_id", school_id)
        .lt("created_at", cutoff)
        .execute()
    )
    for row in expired.data or []:
        url = row.get("attachment_url")
        if url:
            try:
                delete_homework_attachment(school_id, filename_from_attachment_url(url))
            except Exception:
                pass
    await (
        client.table("homework")
        .delete()
        .eq("school_id", school_id)
        .lt("created_at", cutoff)
        .execute()
    )


async def list_homework(
    school_id: str,
    *,
    assigned_by_user_id: Optional[str] = None,
) -> List[HomeworkItem]:
    await purge_expired_homework(school_id)
    client = get_client()
    query = (
        client.table("homework")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .gte("created_at", _cutoff_iso())
    )
    if assigned_by_user_id:
        query = query.eq("assigned_by_user_id", assigned_by_user_id)
    res = await query.order("created_at", desc=True).limit(500).execute()
    return [HomeworkItem(**row) for row in (res.data or [])]


async def get_homework(school_id: str, homework_id: str) -> dict:
    client = get_client()
    res = (
        await client.table("homework")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", homework_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Homework not found")
    return res.data[0]


def assert_can_manage(user: dict, row: dict) -> None:
    if user.get("role") != "teacher":
        return
    owner_id = row.get("assigned_by_user_id")
    if owner_id and owner_id != user["id"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this homework")
    if not owner_id and (row.get("assigned_by") or "") != (user.get("full_name") or ""):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this homework")


_ALL_SECTIONS_LABEL = "All Sections"


def teacher_can_assign(assignments: list[str], class_name: str, section_name: str) -> bool:
    class_key = (class_name or "").strip().lower()
    section_key = (section_name or "").strip().lower()
    if not class_key:
        return False
    specific = f"{class_key} - {section_key}"
    all_sections = f"{class_key} - {_ALL_SECTIONS_LABEL.lower()}"
    for entry in assignments or []:
        value = (entry or "").strip().lower()
        if not value:
            continue
        if value == specific or value == all_sections:
            return True
    return False


async def assert_teacher_can_assign(user: dict, class_name: str, section_name: str) -> None:
    if user.get("role") != "teacher":
        return
    from services import teacher_service

    teacher = await teacher_service.get_teacher_by_user_id(user["school_id"], user["id"])
    if not teacher_can_assign(teacher.classes_teaching or [], class_name, section_name):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You can only assign homework to classes and sections you teach",
        )


async def create_homework(
    school_id: str,
    *,
    subject: str,
    title: str,
    description: str,
    class_name: str,
    due_date: str,
    assigned_by: str,
    assigned_by_user_id: Optional[str] = None,
    section_name: str = "",
    attachment_url: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> HomeworkItem:
    await purge_expired_homework(school_id)
    if not class_name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Class is required")
    if not title.strip() and not description.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Homework message is required")

    client = get_client()
    row = {
        "school_id": school_id,
        "subject": subject.strip() or "Homework",
        "title": title.strip() or (description.strip()[:80] or "Homework"),
        "description": description.strip(),
        "class_name": class_name.strip(),
        "section_name": (section_name or "").strip(),
        "due_date": due_date,
        "assigned_by": assigned_by,
        "assigned_by_user_id": assigned_by_user_id,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
    }
    inserted = await client.table("homework").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create homework")
    return HomeworkItem(**inserted.data[0])


async def update_homework(
    school_id: str,
    homework_id: str,
    *,
    subject: str,
    title: str,
    description: str,
    class_name: str,
    due_date: str,
    section_name: str = "",
    attachment_url: Optional[str] = None,
    attachment_name: Optional[str] = None,
) -> HomeworkItem:
    if not class_name.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Class is required")
    if not title.strip() and not description.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Homework message is required")

    client = get_client()
    patch = {
        "subject": subject.strip() or "Homework",
        "title": title.strip() or (description.strip()[:80] or "Homework"),
        "description": description.strip(),
        "class_name": class_name.strip(),
        "section_name": (section_name or "").strip(),
        "due_date": due_date,
        "attachment_url": attachment_url,
        "attachment_name": attachment_name,
    }
    updated = (
        await client.table("homework")
        .update(patch)
        .eq("school_id", school_id)
        .eq("id", homework_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Homework not found")
    return HomeworkItem(**updated.data[0])


async def delete_homework(school_id: str, homework_id: str) -> None:
    row = await get_homework(school_id, homework_id)
    url = row.get("attachment_url")
    await (
        get_client()
        .table("homework")
        .delete()
        .eq("school_id", school_id)
        .eq("id", homework_id)
        .execute()
    )
    if url:
        try:
            delete_homework_attachment(school_id, filename_from_attachment_url(url))
        except Exception:
            pass
