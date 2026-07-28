"""School calendar — holidays, birthdays, and special days."""
from __future__ import annotations

import calendar as cal
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.calendar import (
    CalendarEventCreateIn,
    CalendarEventOut,
    CalendarEventUpdateIn,
    CalendarMonthOut,
    CalendarSettingsOut,
)

_COLUMNS = "id,school_id,event_type,title,description,event_date,end_date,created_by,created_at"


def _month_bounds(month: int, year: int) -> tuple[date, date]:
    m = max(1, min(12, month))
    y = max(1970, year)
    start = date(y, m, 1)
    end = date(y, m, cal.monthrange(y, m)[1])
    return start, end


def _event_covers_day(event_date: date, end_date: Optional[date], day: date) -> bool:
    end = end_date or event_date
    return event_date <= day <= end


def _row_to_event(row: dict, *, source: str = "school", person_type: Optional[str] = None) -> CalendarEventOut:
    return CalendarEventOut(
        id=row["id"],
        event_type=row["event_type"],
        title=row["title"],
        description=row.get("description"),
        event_date=row["event_date"],
        end_date=row.get("end_date"),
        source=source,
        person_type=person_type,
        created_by=row.get("created_by"),
        created_at=row.get("created_at"),
    )


async def _profile_birthdays(school_id: str, month: int, year: int) -> List[CalendarEventOut]:
    client = get_client()
    events: List[CalendarEventOut] = []

    async def append_from_table(
        table: str,
        person_type: str,
        *,
        select_cols: str = "user_id,dob",
    ) -> None:
        res = await client.table(table).select(select_cols).eq("school_id", school_id).execute()
        rows = [row for row in (res.data or []) if row.get("dob")]
        if not rows:
            return
        user_ids = [row["user_id"] for row in rows if row.get("user_id")]
        users_by_id: dict[str, dict] = {}
        if user_ids:
            users_res = (
                await client.table("users")
                .select("id,full_name,dob")
                .in_("id", user_ids)
                .execute()
            )
            users_by_id = {row["id"]: row for row in (users_res.data or [])}

        for row in rows:
            user_id = row.get("user_id")
            user = users_by_id.get(user_id or "", {})
            dob_raw = row.get("dob") or user.get("dob")
            if not dob_raw:
                continue
            if isinstance(dob_raw, str):
                dob = date.fromisoformat(dob_raw[:10])
            else:
                dob = dob_raw
            if dob.month != month:
                continue
            try:
                event_day = date(year, dob.month, dob.day)
            except ValueError:
                continue
            name = (user.get("full_name") or "Birthday").strip()
            events.append(
                CalendarEventOut(
                    id=f"profile-{person_type}-{user_id or row.get('id')}",
                    event_type="birthday",
                    title=f"{name}'s birthday",
                    description=None,
                    event_date=event_day,
                    end_date=None,
                    source="profile",
                    person_type=person_type,
                )
            )

    await append_from_table("students", "student")
    await append_from_table("teachers", "teacher", select_cols="user_id")
    await append_from_table("staff_profiles", "staff")
    events.sort(key=lambda item: (item.event_date, item.title.lower()))
    return events


async def list_month(school_id: str, month: int, year: int) -> CalendarMonthOut:
    month_start, month_end = _month_bounds(month, year)
    client = get_client()
    res = (
        await client.table("school_calendar_events")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .execute()
    )
    school_events: List[CalendarEventOut] = []
    for row in res.data or []:
        event_date = date.fromisoformat(str(row["event_date"])[:10])
        end_date_raw = row.get("end_date")
        end_date = date.fromisoformat(str(end_date_raw)[:10]) if end_date_raw else None
        event_end = end_date or event_date
        if event_date <= month_end and event_end >= month_start:
            school_events.append(_row_to_event(row))

    profile_events = await _profile_birthdays(school_id, month, year)
    combined = school_events + profile_events
    combined.sort(key=lambda item: (item.event_date, item.title.lower()))
    return CalendarMonthOut(month=month, year=year, events=combined)


async def get_event(school_id: str, event_id: str) -> CalendarEventOut:
    client = get_client()
    res = (
        await client.table("school_calendar_events")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", event_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Calendar event not found")
    return _row_to_event(rows[0])


async def create_event(school_id: str, body: CalendarEventCreateIn, created_by: str) -> CalendarEventOut:
    if body.end_date and body.end_date < body.event_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date cannot be before start date")
    payload = {
        "id": str(uuid.uuid4()),
        "school_id": school_id,
        "event_type": body.event_type,
        "title": body.title.strip(),
        "description": (body.description or "").strip() or None,
        "event_date": body.event_date.isoformat(),
        "end_date": body.end_date.isoformat() if body.end_date else None,
        "created_by": created_by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    client = get_client()
    res = await client.table("school_calendar_events").insert(payload).execute()
    rows = res.data or []
    if not rows:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create calendar event")
    return _row_to_event(rows[0])


async def update_event(
    school_id: str,
    event_id: str,
    body: CalendarEventUpdateIn,
) -> CalendarEventOut:
    existing = await get_event(school_id, event_id)
    event_date = body.event_date or existing.event_date
    end_date = body.end_date if body.end_date is not None else existing.end_date
    if end_date and end_date < event_date:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "End date cannot be before start date")

    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.event_type is not None:
        updates["event_type"] = body.event_type
    if body.title is not None:
        updates["title"] = body.title.strip()
    if body.description is not None:
        updates["description"] = body.description.strip() or None
    if body.event_date is not None:
        updates["event_date"] = body.event_date.isoformat()
    if body.end_date is not None:
        updates["end_date"] = body.end_date.isoformat() if body.end_date else None

    client = get_client()
    res = (
        await client.table("school_calendar_events")
        .update(updates)
        .eq("school_id", school_id)
        .eq("id", event_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        return await get_event(school_id, event_id)
    return _row_to_event(rows[0])


async def delete_event(school_id: str, event_id: str) -> None:
    await get_event(school_id, event_id)
    client = get_client()
    await (
        client.table("school_calendar_events")
        .delete()
        .eq("school_id", school_id)
        .eq("id", event_id)
        .execute()
    )


async def get_settings(school_id: str) -> CalendarSettingsOut:
    client = get_client()
    res = (
        await client.table("schools")
        .select("open_on_sunday")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return CalendarSettingsOut(open_on_sunday=bool(rows[0].get("open_on_sunday")))


async def update_settings(school_id: str, open_on_sunday: bool) -> CalendarSettingsOut:
    client = get_client()
    res = (
        await client.table("schools")
        .update({"open_on_sunday": open_on_sunday})
        .eq("id", school_id)
        .execute()
    )
    rows = res.data or []
    if not rows:
        # Some PostgREST configs omit returning rows; re-read.
        return await get_settings(school_id)
    return CalendarSettingsOut(open_on_sunday=bool(rows[0].get("open_on_sunday")))
