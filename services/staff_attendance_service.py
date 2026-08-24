"""Staff / teacher attendance persistence (1-year retention per school)."""
from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import List, Tuple

from fastapi import HTTPException, status

from database import get_client
from schemas.content import (
    StaffAttendanceDayOut,
    StaffAttendanceMarkIn,
    StaffAttendanceOut,
    StaffAttendancePeriodSummary,
    StaffAttendanceSummaryOut,
    StaffAttendanceTodaySummary,
)

RETENTION_DAYS = 365
_STAFF_COLUMNS = "id,user_id,date,status"
_VALID_STATUSES = frozenset({"present", "absent", "leave"})


def retention_start(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=RETENTION_DAYS - 1)


def parse_attendance_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid date format") from exc


def ensure_attendance_date_allowed(value: str, today: date | None = None) -> str:
    anchor = today or date.today()
    parsed = parse_attendance_date(value)
    if parsed > anchor:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot mark attendance for a future date")
    if parsed < retention_start(anchor):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Attendance is only kept for the last {RETENTION_DAYS} days",
        )
    return parsed.isoformat()


async def list_staff_attendance_for_date(school_id: str, attendance_date: str) -> List[StaffAttendanceOut]:
    normalized = ensure_attendance_date_allowed(attendance_date)
    client = get_client()
    res = (
        await client.table("staff_attendance")
        .select(_STAFF_COLUMNS)
        .eq("school_id", school_id)
        .eq("date", normalized)
        .order("created_at", desc=False)
        .execute()
    )
    return [StaffAttendanceOut(**row) for row in (res.data or [])]


async def list_staff_attendance_for_range(
    school_id: str,
    from_date: str,
    to_date: str,
) -> List[StaffAttendanceOut]:
    start = ensure_attendance_date_allowed(from_date)
    end = ensure_attendance_date_allowed(to_date)
    if start > end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "from_date must be on or before to_date")

    start_parsed = parse_attendance_date(start)
    end_parsed = parse_attendance_date(end)
    if (end_parsed - start_parsed).days > RETENTION_DAYS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Date range cannot exceed {RETENTION_DAYS} days",
        )

    client = get_client()
    res = (
        await client.table("staff_attendance")
        .select(_STAFF_COLUMNS)
        .eq("school_id", school_id)
        .gte("date", start)
        .lte("date", end)
        .order("date", desc=False)
        .execute()
    )
    return [StaffAttendanceOut(**row) for row in (res.data or [])]


async def _purge_expired_attendance(school_id: str, today: date | None = None) -> None:
    cutoff = retention_start(today or date.today()).isoformat()
    client = get_client()
    await client.table("staff_attendance").delete().eq("school_id", school_id).lt("date", cutoff).execute()


async def mark_staff_attendance(
    school_id: str,
    body: StaffAttendanceMarkIn,
    marked_by: str,
) -> StaffAttendanceOut:
    if body.status not in _VALID_STATUSES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid attendance status")

    normalized_date = ensure_attendance_date_allowed(body.date)
    client = get_client()

    teacher = (
        await client.table("teachers")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", body.user_id)
        .limit(1)
        .execute()
    )
    if not teacher.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")

    existing = (
        await client.table("staff_attendance")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", body.user_id)
        .eq("date", normalized_date)
        .limit(1)
        .execute()
    )
    payload = {
        "status": body.status,
        "marked_by": marked_by,
    }
    if existing.data:
        updated = (
            await client.table("staff_attendance")
            .update(payload)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
        if not updated.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update attendance")
        row = updated.data[0]
    else:
        inserted = (
            await client.table("staff_attendance")
            .insert(
                {
                    "school_id": school_id,
                    "user_id": body.user_id,
                    "date": normalized_date,
                    **payload,
                }
            )
            .execute()
        )
        if not inserted.data:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to mark attendance")
        row = inserted.data[0]

    await _purge_expired_attendance(school_id)
    return StaffAttendanceOut(
        id=row["id"],
        user_id=row["user_id"],
        date=row["date"],
        status=row["status"],
    )


async def list_staff_attendance_for_user(
    school_id: str,
    user_id: str,
    *,
    limit: int = 100,
) -> List[StaffAttendanceOut]:
    """Attendance history for one staff/teacher user (newest first)."""
    await _purge_expired_attendance(school_id)
    client = get_client()
    res = (
        await client.table("staff_attendance")
        .select(_STAFF_COLUMNS)
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .order("date", desc=True)
        .limit(limit)
        .execute()
    )
    return [StaffAttendanceOut(**row) for row in (res.data or [])]


def _parse_iso_date(value: str) -> date:
    return date.fromisoformat(value)


def _iter_dates(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _is_sunday(day: date) -> bool:
    return day.weekday() == 6


def _is_holiday(day: date, holiday_ranges: List[Tuple[date, date]]) -> bool:
    return any(start <= day <= end for start, end in holiday_ranges)


def _period_bounds_for_view(view: str, year: int, month: int, today: date) -> tuple[date, date]:
    if view == "yearly":
        start = date(year, 1, 1)
        if year < today.year:
            end = date(year, 12, 31)
        elif year > today.year:
            end = start
        else:
            end = today
        return start, end

    last_day = calendar.monthrange(year, month)[1]
    start = date(year, month, 1)
    if year < today.year or (year == today.year and month < today.month):
        end = date(year, month, last_day)
    elif year > today.year or (year == today.year and month > today.month):
        end = start
    else:
        end = today
    return start, end


def _period_label(view: str, year: int, month: int) -> str:
    if view == "yearly":
        return str(year)
    anchor = date(year, month, 1)
    return anchor.strftime("%B %Y")


def _summarize_period(
    start: date,
    end: date,
    marks_by_date: dict[str, str],
    holiday_ranges: List[Tuple[date, date]],
) -> StaffAttendancePeriodSummary:
    working_days = 0
    present_days = 0
    absent_days = 0
    if start > end:
        return StaffAttendancePeriodSummary(
            working_days=0,
            present_days=0,
            absent_days=0,
            pct=0,
        )

    for day in _iter_dates(start, end):
        if _is_sunday(day) or _is_holiday(day, holiday_ranges):
            continue
        working_days += 1
        status = marks_by_date.get(day.isoformat())
        if status == "present":
            present_days += 1
        elif status == "absent":
            absent_days += 1
    pct = round((present_days / working_days) * 100) if working_days else 0
    return StaffAttendancePeriodSummary(
        working_days=working_days,
        present_days=present_days,
        absent_days=absent_days,
        pct=pct,
    )


def _today_label(
    today: date,
    marks_by_date: dict[str, str],
    holiday_ranges: List[Tuple[date, date]],
) -> StaffAttendanceTodaySummary:
    if _is_sunday(today) or _is_holiday(today, holiday_ranges):
        return StaffAttendanceTodaySummary(label="Holiday", is_holiday=True)

    status = marks_by_date.get(today.isoformat())
    label_by_status = {
        "present": "Present",
        "absent": "Absent",
        "leave": "On Leave",
    }
    return StaffAttendanceTodaySummary(
        label=label_by_status.get(status or "", "Not Marked"),
        is_holiday=False,
    )


def _period_days(
    start: date,
    end: date,
    marks_by_date: dict[str, str],
    holiday_ranges: List[Tuple[date, date]],
) -> List[StaffAttendanceDayOut]:
    if start > end:
        return []

    label_by_status = {
        "present": "Present",
        "absent": "Absent",
        "leave": "On Leave",
    }
    days: List[StaffAttendanceDayOut] = []
    for day in _iter_dates(start, end):
        if _is_sunday(day) or _is_holiday(day, holiday_ranges):
            continue
        status = marks_by_date.get(day.isoformat()) or "not_marked"
        days.append(
            StaffAttendanceDayOut(
                date=day.isoformat(),
                status=status,
                status_label=label_by_status.get(status, "Not Marked"),
            )
        )
    days.reverse()
    return days


async def _holiday_ranges_for_year(school_id: str, year: int) -> List[Tuple[date, date]]:
    client = get_client()
    start = date(year, 1, 1).isoformat()
    end = date(year, 12, 31).isoformat()
    res = (
        await client.table("school_calendar_events")
        .select("event_date,end_date,event_type")
        .eq("school_id", school_id)
        .eq("event_type", "holiday")
        .lte("event_date", end)
        .execute()
    )
    ranges: List[Tuple[date, date]] = []
    for row in res.data or []:
        event_start = _parse_iso_date(row["event_date"])
        event_end = _parse_iso_date(row.get("end_date") or row["event_date"])
        if event_end < date(year, 1, 1) or event_start > date(year, 12, 31):
            continue
        ranges.append((event_start, event_end))
    return ranges


async def my_staff_attendance_summary(
    user: dict,
    *,
    view: str = "monthly",
    month: int | None = None,
    year: int | None = None,
) -> StaffAttendanceSummaryOut:
    if view not in {"monthly", "yearly"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "view must be monthly or yearly")

    school_id = user["school_id"]
    user_id = user["id"]
    today = date.today()
    selected_year = year or today.year
    selected_month = month or today.month
    if selected_month < 1 or selected_month > 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be between 1 and 12")

    retention_start_date = retention_start(today)
    period_start, period_end = _period_bounds_for_view(
        view,
        selected_year,
        selected_month,
        today,
    )
    fetch_start = min(period_start, retention_start_date)
    marks = await list_staff_attendance_for_range(
        school_id,
        max(fetch_start, retention_start_date).isoformat(),
        max(period_end, period_start).isoformat(),
    )
    marks_by_date = {
        row.date: row.status for row in marks if row.user_id == user_id
    }

    holiday_years = {period_start.year, period_end.year, today.year}
    holiday_ranges: List[Tuple[date, date]] = []
    for holiday_year in sorted(holiday_years):
        holiday_ranges.extend(await _holiday_ranges_for_year(school_id, holiday_year))

    clamped_start = max(period_start, retention_start_date)
    return StaffAttendanceSummaryOut(
        period=_summarize_period(clamped_start, period_end, marks_by_date, holiday_ranges),
        today=_today_label(today, marks_by_date, holiday_ranges),
        period_label=_period_label(view, selected_year, selected_month),
        days=_period_days(clamped_start, period_end, marks_by_date, holiday_ranges),
    )


async def my_student_attendance_summary(
    user: dict,
    *,
    view: str = "monthly",
    month: int | None = None,
    year: int | None = None,
) -> StaffAttendanceSummaryOut:
    """Student's own attendance summary — mirrors my_staff_attendance_summary
    but queries the ``attendance`` table by ``student_email``."""
    if view not in {"monthly", "yearly"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "view must be monthly or yearly")

    school_id = user["school_id"]
    student_email = (user.get("email") or "").strip().lower()
    if not student_email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student email not found")

    today = date.today()
    selected_year = year or today.year
    selected_month = month or today.month
    if selected_month < 1 or selected_month > 12:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month must be between 1 and 12")

    retention_start_date = retention_start(today)
    period_start, period_end = _period_bounds_for_view(
        view,
        selected_year,
        selected_month,
        today,
    )

    fetch_start = min(period_start, retention_start_date)
    client = get_client()
    res = (
        await client.table("attendance")
        .select("date,status")
        .eq("school_id", school_id)
        .eq("student_email", student_email)
        .gte("date", max(fetch_start, retention_start_date).isoformat())
        .lte("date", max(period_end, period_start).isoformat())
        .execute()
    )
    marks_by_date: dict[str, str] = {}
    for row in res.data or []:
        key = str(row.get("date") or "").strip()
        status = str(row.get("status") or "").strip().lower()
        if key and status:
            marks_by_date[key] = status

    holiday_years = {period_start.year, period_end.year, today.year}
    holiday_ranges: List[Tuple[date, date]] = []
    for holiday_year in sorted(holiday_years):
        holiday_ranges.extend(await _holiday_ranges_for_year(school_id, holiday_year))

    clamped_start = max(period_start, retention_start_date)
    return StaffAttendanceSummaryOut(
        period=_summarize_period(clamped_start, period_end, marks_by_date, holiday_ranges),
        today=_today_label(today, marks_by_date, holiday_ranges),
        period_label=_period_label(view, selected_year, selected_month),
        days=_period_days(clamped_start, period_end, marks_by_date, holiday_ranges),
    )
