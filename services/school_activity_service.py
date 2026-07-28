"""Aggregate recent school events for the admin home live activity feed."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from database import get_client

_STAFF_ROLES = frozenset(
    {
        "receptionist",
        "accountant",
        "librarian",
        "hostel_manager",
        "transport_manager",
        "school_doctor",
    }
)
_ROLE_LABELS = {
    "receptionist": "Receptionist",
    "accountant": "Accountant",
    "librarian": "Librarian",
    "hostel_manager": "Hostel Warden",
    "transport_manager": "Transport Manager",
    "school_doctor": "School Doctor",
}


def _parse_ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _bucket_minute(ts: datetime, minutes: int = 10) -> datetime:
    ts = ts.astimezone(timezone.utc).replace(second=0, microsecond=0)
    return ts.replace(minute=(ts.minute // minutes) * minutes)


async def _attendance_activities(school_id: str, since: datetime) -> List[dict]:
    client = get_client()
    res = (
        await client.table("attendance")
        .select("class_name,date,marked_by,created_at")
        .eq("school_id", school_id)
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(400)
        .execute()
    )
    grouped: Dict[tuple, dict] = {}
    for row in res.data or []:
        created = _parse_ts(row.get("created_at"))
        class_name = (row.get("class_name") or "Class").strip() or "Class"
        marker = (row.get("marked_by") or "Teacher").strip() or "Teacher"
        date_label = str(row.get("date") or "")
        bucket = _bucket_minute(created)
        key = (class_name, date_label, marker, bucket.isoformat())
        entry = grouped.get(key)
        if not entry:
            grouped[key] = {
                "id": f"attendance-{class_name}-{date_label}-{marker}-{bucket.isoformat()}",
                "type": "attendance_marked",
                "title": f"Attendance taken for {class_name}",
                "subtitle": f"{marker} · {date_label}",
                "occurred_at": created,
                "count": 1,
            }
        else:
            entry["count"] += 1
            if created > entry["occurred_at"]:
                entry["occurred_at"] = created
    out = list(grouped.values())
    for item in out:
        if item["count"] > 1:
            item["subtitle"] = f"{item['subtitle']} · {item['count']} students"
        del item["count"]
    return out


async def _fee_activities(school_id: str, since: datetime) -> List[dict]:
    """Fee payments (incl. custom/partial) + manually added dues for live activity."""
    client = get_client()
    items: List[dict] = []
    payments: List[dict] = []

    try:
        pay_res = (
            await client.table("payments")
            .select("id,amount,paid_at,fee_id,method")
            .eq("school_id", school_id)
            .gte("paid_at", since.isoformat())
            .order("paid_at", desc=True)
            .limit(40)
            .execute()
        )
        payments = pay_res.data or []
    except Exception:
        payments = []

    fee_ids = [str(p["fee_id"]) for p in payments if p.get("fee_id")]
    fee_by_id: dict[str, dict] = {}
    if fee_ids:
        try:
            fees_res = (
                await client.table("fees")
                .select("id,title,student_email")
                .eq("school_id", school_id)
                .in_("id", fee_ids)
                .execute()
            )
            for row in fees_res.data or []:
                fee_by_id[str(row["id"])] = row
        except Exception:
            fee_by_id = {}

    emails = {
        (fee_by_id.get(str(p["fee_id"]), {}).get("student_email") or "").strip().lower()
        for p in payments
        if p.get("fee_id")
    }

    due_res = (
        await client.table("fees")
        .select("id,title,amount,student_email,created_at")
        .eq("school_id", school_id)
        .ilike("title", "Additional due%")
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    for row in due_res.data or []:
        if row.get("student_email"):
            emails.add((row.get("student_email") or "").strip().lower())
    emails.discard("")

    name_by_email: dict[str, str] = {}
    if emails:
        users_res = (
            await client.table("users")
            .select("email,full_name")
            .eq("school_id", school_id)
            .in_("email", list(emails))
            .execute()
        )
        for u in users_res.data or []:
            email = (u.get("email") or "").strip().lower()
            if email:
                name_by_email[email] = (u.get("full_name") or email.split("@")[0]).strip()

    for p in payments:
        paid_at = p.get("paid_at")
        if not paid_at:
            continue
        fee = fee_by_id.get(str(p["fee_id"]), {}) if p.get("fee_id") else {}
        amount = p.get("amount") or 0
        email = (fee.get("student_email") or "").strip().lower()
        student = name_by_email.get(email) or (email.split("@")[0] if email else "Student")
        method = (p.get("method") or "").strip().lower()
        if method == "custom":
            activity_title = "Custom pay"
        else:
            activity_title = "Fees paid"
        items.append(
            {
                "id": f"fee-pay-{p['id']}",
                "type": "fee_paid",
                "title": activity_title,
                "subtitle": f"{student} · ₹{amount}",
                "amount": float(amount),
                "sign": "-",
                "occurred_at": _parse_ts(paid_at),
            }
        )

    for row in due_res.data or []:
        created_at = row.get("created_at")
        if not created_at:
            continue
        amount = row.get("amount") or 0
        raw_title = (row.get("title") or "Additional due").strip()
        reason = raw_title
        if "—" in reason and reason.lower().startswith("additional due"):
            reason = reason.split("—", 1)[1].strip() or "Additional due"
        elif reason.lower().startswith("additional due -"):
            reason = reason.split("-", 1)[1].strip() or "Additional due"
        email = (row.get("student_email") or "").strip().lower()
        student = name_by_email.get(email) or (email.split("@")[0] if email else "Student")
        subtitle = f"{student} · {reason} · ₹{amount}" if reason.lower() != "additional due" else f"{student} · ₹{amount}"
        items.append(
            {
                "id": f"fee-due-{row['id']}",
                "type": "fee_due_added",
                "title": "Add due",
                "subtitle": subtitle,
                "amount": float(amount),
                "sign": "+",
                "occurred_at": _parse_ts(created_at),
            }
        )
    return items


async def _announcement_activities(school_id: str, since: datetime) -> List[dict]:
    client = get_client()
    res = (
        await client.table("announcements")
        .select("id,title,author,created_at")
        .eq("school_id", school_id)
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return [
        {
            "id": f"announcement-{row['id']}",
            "type": "announcement_created",
            "title": "New announcement published",
            "subtitle": f"{row.get('title') or 'Announcement'} · {row.get('author') or 'Admin'}",
            "occurred_at": _parse_ts(row.get("created_at")),
        }
        for row in (res.data or [])
    ]


async def _user_added_activities(
    school_id: str,
    since: datetime,
    role: str,
    activity_type: str,
    label: str,
) -> List[dict]:
    client = get_client()
    res = (
        await client.table("users")
        .select("id,full_name,created_at")
        .eq("school_id", school_id)
        .eq("role", role)
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(15)
        .execute()
    )
    return [
        {
            "id": f"{activity_type}-{row['id']}",
            "type": activity_type,
            "title": f"New {label} added",
            "subtitle": row.get("full_name") or label,
            "occurred_at": _parse_ts(row.get("created_at")),
        }
        for row in (res.data or [])
    ]


async def _staff_added_activities(school_id: str, since: datetime) -> List[dict]:
    client = get_client()
    res = (
        await client.table("users")
        .select("id,full_name,role,created_at")
        .eq("school_id", school_id)
        .in_("role", list(_STAFF_ROLES))
        .gte("created_at", since.isoformat())
        .order("created_at", desc=True)
        .limit(15)
        .execute()
    )
    items: List[dict] = []
    for row in res.data or []:
        role = row.get("role") or "staff"
        label = _ROLE_LABELS.get(role, "Staff member")
        items.append(
            {
                "id": f"staff-{row['id']}",
                "type": "staff_added",
                "title": f"New {label} added",
                "subtitle": row.get("full_name") or label,
                "occurred_at": _parse_ts(row.get("created_at")),
            }
        )
    return items


async def _school_timing_activities(school_id: str, since: datetime) -> List[dict]:
    client = get_client()
    res = (
        await client.table("school_timing")
        .select("start_time,end_time,start_meridiem,end_meridiem,updated_at")
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return []
    row = res.data[0]
    updated = _parse_ts(row.get("updated_at"))
    if updated < since:
        return []
    start = f"{row.get('start_time') or '--'} {row.get('start_meridiem') or ''}".strip()
    end = f"{row.get('end_time') or '--'} {row.get('end_meridiem') or ''}".strip()
    return [
        {
            "id": f"school-timing-{school_id}",
            "type": "school_timing_updated",
            "title": "School timing updated",
            "subtitle": f"{start} – {end}",
            "occurred_at": updated,
        }
    ]


async def _period_timing_activities(school_id: str, since: datetime) -> List[dict]:
    client = get_client()
    res = (
        await client.table("period_timetables")
        .select("id,period_count,times_saved,updated_at")
        .eq("school_id", school_id)
        .gte("updated_at", since.isoformat())
        .order("updated_at", desc=True)
        .limit(10)
        .execute()
    )
    items: List[dict] = []
    for row in res.data or []:
        periods = row.get("period_count") or 0
        detail = f"{periods} periods"
        if row.get("times_saved"):
            detail += " · times saved"
        items.append(
            {
                "id": f"period-timing-{row['id']}",
                "type": "period_timing_updated",
                "title": "Period timing updated",
                "subtitle": detail,
                "occurred_at": _parse_ts(row.get("updated_at")),
            }
        )
    return items


async def list_school_live_activity(school_id: str, *, days: int = 30, limit: int = 10) -> List[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    chunks = await _gather_all(school_id, since)
    merged = [item for group in chunks for item in group]
    merged.sort(key=lambda item: item["occurred_at"], reverse=True)
    return merged[:limit]


async def _gather_all(school_id: str, since: datetime) -> List[List[dict]]:
    import asyncio

    results = await asyncio.gather(
        _attendance_activities(school_id, since),
        _fee_activities(school_id, since),
        _announcement_activities(school_id, since),
        _user_added_activities(school_id, since, "student", "student_added", "student"),
        _user_added_activities(school_id, since, "teacher", "teacher_added", "teacher"),
        _staff_added_activities(school_id, since),
        _school_timing_activities(school_id, since),
        _period_timing_activities(school_id, since),
        return_exceptions=True,
    )
    out: List[List[dict]] = []
    for chunk in results:
        if isinstance(chunk, Exception):
            continue
        out.append(chunk)
    return out
