"""School timing and period timetable storage per school."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.content import (
    PeriodSlotIn,
    PeriodSlotOut,
    PeriodTimetableClassIn,
    PeriodTimetableCreateIn,
    PeriodTimetableOut,
    PeriodTimetableUpdateIn,
    SchoolTimingOut,
    SchoolTimingUpsertIn,
)

_MERIDIEM = frozenset({"AM", "PM"})


def _validate_meridiem(value: str, field: str) -> str:
    upper = (value or "").strip().upper()
    if upper not in _MERIDIEM:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid {field}")
    return upper


def _validate_school_timing(body: SchoolTimingUpsertIn) -> dict:
    start_time = (body.start_time or "").strip()
    end_time = (body.end_time or "").strip()
    if not start_time or not end_time:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Start and end time are required")
    return {
        "start_time": start_time,
        "start_meridiem": _validate_meridiem(body.start_meridiem, "start_meridiem"),
        "end_time": end_time,
        "end_meridiem": _validate_meridiem(body.end_meridiem, "end_meridiem"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def _empty_slots(count: int) -> List[dict]:
    return [
        {
            "period_index": index,
            "start_time": "",
            "start_meridiem": "AM",
            "end_time": "",
            "end_meridiem": "AM",
        }
        for index in range(count)
    ]


def _merge_slots(existing: List[dict], count: int) -> List[PeriodSlotIn]:
    by_index = {row["period_index"]: row for row in existing}
    merged: List[PeriodSlotIn] = []
    for index in range(count):
        row = by_index.get(index, {})
        merged.append(
            PeriodSlotIn(
                start_time=row.get("start_time") or "",
                start_meridiem=row.get("start_meridiem") or "AM",
                end_time=row.get("end_time") or "",
                end_meridiem=row.get("end_meridiem") or "AM",
            )
        )
    return merged


async def _fetch_classes(client, timetable_id: str) -> List[PeriodTimetableClassIn]:
    res = (
        await client.table("period_timetable_classes")
        .select("class_id,class_name")
        .eq("timetable_id", timetable_id)
        .order("class_name")
        .execute()
    )
    return [
        PeriodTimetableClassIn(class_id=row["class_id"], class_name=row["class_name"])
        for row in (res.data or [])
    ]


async def _fetch_slots(client, timetable_id: str) -> List[PeriodSlotOut]:
    res = (
        await client.table("period_timetable_slots")
        .select("period_index,start_time,start_meridiem,end_time,end_meridiem")
        .eq("timetable_id", timetable_id)
        .order("period_index")
        .execute()
    )
    return [
        PeriodSlotOut(
            period_index=row["period_index"],
            start_time=row.get("start_time") or "",
            start_meridiem=row.get("start_meridiem") or "AM",
            end_time=row.get("end_time") or "",
            end_meridiem=row.get("end_meridiem") or "AM",
        )
        for row in (res.data or [])
    ]


def _normalize_classes(classes: List[PeriodTimetableClassIn]) -> List[PeriodTimetableClassIn]:
    if not classes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Select at least one class")
    seen: set[str] = set()
    normalized: List[PeriodTimetableClassIn] = []
    for item in classes:
        if item.class_id in seen:
            continue
        seen.add(item.class_id)
        normalized.append(item)
    return normalized


async def _assert_classes_available(
    client,
    school_id: str,
    classes: List[PeriodTimetableClassIn],
    *,
    exclude_timetable_id: Optional[str] = None,
) -> None:
    for class_item in classes:
        await _assert_class_available(
            client,
            school_id,
            class_item.class_id,
            class_name=class_item.class_name,
            exclude_timetable_id=exclude_timetable_id,
        )


async def _assert_class_available(
    client,
    school_id: str,
    class_id: str,
    *,
    class_name: str = "This class",
    exclude_timetable_id: Optional[str] = None,
) -> None:
    res = (
        await client.table("period_timetable_classes")
        .select("timetable_id,class_name")
        .eq("class_id", class_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return
    row = res.data[0]
    timetable_id = row["timetable_id"]
    if exclude_timetable_id and timetable_id == exclude_timetable_id:
        return
    owner = (
        await client.table("period_timetables")
        .select("id")
        .eq("id", timetable_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if owner.data:
        label = row.get("class_name") or class_name
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"{label} already has a timetable",
        )


async def _to_timetable_out(client, row: dict) -> PeriodTimetableOut:
    timetable_id = row["id"]
    return PeriodTimetableOut(
        id=timetable_id,
        classes=await _fetch_classes(client, timetable_id),
        period_count=row["period_count"],
        periods=await _fetch_slots(client, timetable_id),
        times_saved=bool(row.get("times_saved")),
    )


async def get_school_timing(school_id: str) -> Optional[SchoolTimingOut]:
    client = get_client()
    res = await client.table("school_timing").select("*").eq("school_id", school_id).limit(1).execute()
    if not res.data:
        return None
    row = res.data[0]
    return SchoolTimingOut(
        start_time=row.get("start_time") or "",
        start_meridiem=row.get("start_meridiem") or "AM",
        end_time=row.get("end_time") or "",
        end_meridiem=row.get("end_meridiem") or "PM",
        updated_at=row.get("updated_at"),
    )


async def upsert_school_timing(school_id: str, body: SchoolTimingUpsertIn) -> SchoolTimingOut:
    client = get_client()
    payload = {"school_id": school_id, **_validate_school_timing(body)}
    res = await client.table("school_timing").upsert(payload, on_conflict="school_id").execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save school timing")
    row = res.data[0]
    return SchoolTimingOut(
        start_time=row.get("start_time") or "",
        start_meridiem=row.get("start_meridiem") or "AM",
        end_time=row.get("end_time") or "",
        end_meridiem=row.get("end_meridiem") or "PM",
        updated_at=row.get("updated_at"),
    )


async def list_period_timetables(school_id: str) -> List[PeriodTimetableOut]:
    client = get_client()
    res = (
        await client.table("period_timetables")
        .select("id,period_count,times_saved,updated_at")
        .eq("school_id", school_id)
        .order("updated_at", desc=True)
        .execute()
    )
    rows = res.data or []
    return [await _to_timetable_out(client, row) for row in rows]


async def create_period_timetable(
    school_id: str,
    body: PeriodTimetableCreateIn,
) -> PeriodTimetableOut:
    classes = _normalize_classes(body.classes)
    client = get_client()
    await _assert_classes_available(client, school_id, classes)

    now = datetime.now(timezone.utc).isoformat()
    inserted = (
        await client.table("period_timetables")
        .insert(
            {
                "school_id": school_id,
                "period_count": body.period_count,
                "times_saved": False,
                "created_at": now,
                "updated_at": now,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create timetable")
    timetable_id = inserted.data[0]["id"]

    await client.table("period_timetable_classes").insert(
        [
            {
                "timetable_id": timetable_id,
                "class_id": class_item.class_id,
                "class_name": class_item.class_name,
            }
            for class_item in classes
        ]
    ).execute()

    await client.table("period_timetable_slots").insert(
        [
            {
                "timetable_id": timetable_id,
                **slot,
            }
            for slot in _empty_slots(body.period_count)
        ]
    ).execute()

    return await _to_timetable_out(client, inserted.data[0])


async def update_period_timetable(
    school_id: str,
    timetable_id: str,
    body: PeriodTimetableUpdateIn,
) -> PeriodTimetableOut:
    client = get_client()
    existing = (
        await client.table("period_timetables")
        .select("id,period_count,times_saved")
        .eq("id", timetable_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timetable not found")

    row = existing.data[0]
    period_count = body.period_count if body.period_count is not None else row["period_count"]
    times_saved = body.times_saved if body.times_saved is not None else row["times_saved"]

    if body.periods is not None:
        if len(body.periods) != period_count:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Period slots must match the number of periods",
            )
        if times_saved:
            for index, slot in enumerate(body.periods):
                if not slot.start_time.strip() or not slot.end_time.strip():
                    raise HTTPException(
                        status.HTTP_400_BAD_REQUEST,
                        f"Enter start and end time for period {index + 1}",
                    )
                _validate_meridiem(slot.start_meridiem, "start_meridiem")
                _validate_meridiem(slot.end_meridiem, "end_meridiem")

    now = datetime.now(timezone.utc).isoformat()
    await (
        client.table("period_timetables")
        .update(
            {
                "period_count": period_count,
                "times_saved": times_saved,
                "updated_at": now,
            }
        )
        .eq("id", timetable_id)
        .eq("school_id", school_id)
        .execute()
    )

    if body.classes is not None:
        classes = _normalize_classes(body.classes)
        await _assert_classes_available(
            client,
            school_id,
            classes,
            exclude_timetable_id=timetable_id,
        )
        await client.table("period_timetable_classes").delete().eq("timetable_id", timetable_id).execute()
        await client.table("period_timetable_classes").insert(
            [
                {
                    "timetable_id": timetable_id,
                    "class_id": class_item.class_id,
                    "class_name": class_item.class_name,
                }
                for class_item in classes
            ]
        ).execute()

    if body.periods is not None:
        await client.table("period_timetable_slots").delete().eq("timetable_id", timetable_id).execute()
        await client.table("period_timetable_slots").insert(
            [
                {
                    "timetable_id": timetable_id,
                    "period_index": index,
                    "start_time": slot.start_time.strip(),
                    "start_meridiem": _validate_meridiem(slot.start_meridiem, "start_meridiem"),
                    "end_time": slot.end_time.strip(),
                    "end_meridiem": _validate_meridiem(slot.end_meridiem, "end_meridiem"),
                }
                for index, slot in enumerate(body.periods)
            ]
        ).execute()
    elif body.period_count is not None and body.period_count != row["period_count"]:
        current_slots = await _fetch_slots(client, timetable_id)
        merged = _merge_slots(
            [slot.model_dump() for slot in current_slots],
            period_count,
        )
        await client.table("period_timetable_slots").delete().eq("timetable_id", timetable_id).execute()
        await client.table("period_timetable_slots").insert(
            [
                {
                    "timetable_id": timetable_id,
                    "period_index": index,
                    "start_time": slot.start_time,
                    "start_meridiem": slot.start_meridiem,
                    "end_time": slot.end_time,
                    "end_meridiem": slot.end_meridiem,
                }
                for index, slot in enumerate(merged)
            ]
        ).execute()

    refreshed = (
        await client.table("period_timetables")
        .select("id,period_count,times_saved")
        .eq("id", timetable_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    return await _to_timetable_out(client, refreshed.data[0])


async def delete_period_timetable(school_id: str, timetable_id: str) -> None:
    client = get_client()
    res = (
        await client.table("period_timetables")
        .delete()
        .eq("id", timetable_id)
        .eq("school_id", school_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Timetable not found")
