"""Announcements per school with rolling 1-year retention."""
from __future__ import annotations

import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status

from database import get_client
from schemas.content import Announcement

_COLUMNS = (
    "id,school_id,title,body,audience,author,"
    "attachment_url,attachment_name,recipient_user_id,recipient_name,recipient_type,recipients,"
    "audience_targets,created_at"
)
ANNOUNCEMENT_RETENTION_DAYS = 365


def retention_start(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=ANNOUNCEMENT_RETENTION_DAYS - 1)


def _month_bounds(month: int, year: int) -> Tuple[str, str]:
    m = max(1, min(12, month))
    y = max(1970, year)
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start.isoformat(), end.isoformat()


def _parse_date(value: str) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid date") from exc


def _day_range(on_date: str) -> Tuple[str, str]:
    parsed = _parse_date(on_date)
    return f"{parsed}T00:00:00+00:00", f"{parsed}T23:59:59.999999+00:00"


def _month_range(month: int, year: int) -> Tuple[str, str]:
    start, end = _month_bounds(month, year)
    return f"{start}T00:00:00+00:00", f"{end}T23:59:59.999999+00:00"


async def purge_expired_announcements(school_id: str, today: date | None = None) -> None:
    from utils.ttl_cache import should_run

    if not should_run(f"purge_announcements:{school_id}", ttl_seconds=300):
        return
    cutoff = datetime.combine(
        retention_start(today or date.today()),
        time.min,
        tzinfo=timezone.utc,
    ).isoformat()
    client = get_client()
    await (
        client.table("announcements")
        .delete()
        .eq("school_id", school_id)
        .lt("created_at", cutoff)
        .execute()
    )


async def list_announcements(
    school_id: str,
    *,
    audience: Optional[str] = None,
    month: Optional[int] = None,
    year: Optional[int] = None,
    on_date: Optional[str] = None,
) -> List[Announcement]:
    await purge_expired_announcements(school_id)
    client = get_client()
    query = client.table("announcements").select(_COLUMNS).eq("school_id", school_id)

    if on_date is not None:
        start_at, end_at = _day_range(on_date)
        query = query.gte("created_at", start_at).lte("created_at", end_at)
    elif month is not None and year is not None:
        start_at, end_at = _month_range(month, year)
        query = query.gte("created_at", start_at).lte("created_at", end_at)

    if audience == "everyone":
        query = query.in_("audience", ["all", "school"])
    elif audience:
        query = query.eq("audience", audience)

    res = await query.order("created_at", desc=True).limit(200).execute()
    return [Announcement(**row) for row in (res.data or [])]


def _recipient_user_ids(announcement: Announcement) -> set[str]:
    ids = {item.user_id for item in (announcement.recipients or []) if item.user_id}
    if announcement.recipient_user_id:
        ids.add(announcement.recipient_user_id)
    return ids


async def student_class_placement(school_id: str, user_id: str) -> Optional[dict]:
    """Return {class_id, section_id} for a student user, or None."""
    if not user_id:
        return None
    client = get_client()
    res = (
        await client.table("students")
        .select("class_id,section_id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    return {"class_id": row.get("class_id"), "section_id": row.get("section_id")}


def _targets_dict(announcement: Announcement) -> dict:
    targets = announcement.audience_targets
    if targets is None:
        return {}
    if hasattr(targets, "model_dump"):
        return targets.model_dump()
    if isinstance(targets, dict):
        return targets
    return {}


def announcement_visible_to_user(
    announcement: Announcement,
    user: dict,
    *,
    student_placement: Optional[dict] = None,
) -> bool:
    audience = announcement.audience
    role = user.get("role") or ""
    user_id = user.get("id") or ""

    if audience in {"all", "school"}:
        return True
    if audience == "teachers" and role == "teacher":
        return True
    if audience == "students" and role == "student":
        return True
    if audience == "specific":
        return bool(user_id and user_id in _recipient_user_ids(announcement))
    if audience == "class":
        if role != "student" or not student_placement:
            return False
        targets = _targets_dict(announcement)
        class_ids = {str(x) for x in (targets.get("class_ids") or []) if x}
        section_ids = {str(x) for x in (targets.get("section_ids") or []) if x}
        all_sections = bool(targets.get("all_sections", True))
        class_id = student_placement.get("class_id")
        section_id = student_placement.get("section_id")
        if not class_ids or not class_id or str(class_id) not in class_ids:
            return False
        if all_sections or not section_ids:
            return True
        return bool(section_id and str(section_id) in section_ids)
    return False


async def list_announcements_for_user(
    school_id: str,
    user: dict,
    *,
    limit: int = 5,
) -> List[Announcement]:
    await purge_expired_announcements(school_id)
    client = get_client()
    res = (
        await client.table("announcements")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .limit(100)
        .execute()
    )
    rows = [Announcement(**row) for row in (res.data or [])]
    placement = None
    if (user.get("role") or "") == "student":
        placement = await student_class_placement(school_id, user.get("id") or "")
    matched = [
        row
        for row in rows
        if announcement_visible_to_user(row, user, student_placement=placement)
    ]
    capped = max(1, min(limit, 20))
    return matched[:capped]
