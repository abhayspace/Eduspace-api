"""Root health check + aggregate stats."""
import asyncio
import calendar
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends

from database import get_client
from schemas.activity import SchoolActivityOut
from services import school_activity_service
from utils.deps import current_user

router = APIRouter(tags=["misc"])

STAFF_ROLES = [
    "receptionist",
    "accountant",
    "librarian",
    "hostel_manager",
    "transport_manager",
    "school_doctor",
    "principal",
    "vice_principal",
]


@router.get("/")
async def root() -> dict:
    return {"app": "EduSpace", "status": "ok"}


async def _count(table: str, school_id: str, **filters) -> int:
    client = get_client()
    query = (
        client.table(table)
        .select("*", count="exact", head=True)
        .eq("school_id", school_id)
    )
    for key, value in filters.items():
        query = query.eq(key, value)
    res = await query.execute()
    return res.count if res.count is not None else 0


async def _sum_pending_fees(school_id: str) -> float:
    """Total amount due across pending fee rows for the school (paid excluded)."""
    from services import fee_structure_service

    return await fee_structure_service.sum_pending_fees(school_id, ensure_monthly=True)


async def _count_students(school_id: str) -> int:
    """Count student profiles (matches Student Module list)."""
    return await _count("students", school_id)


async def _student_attendance_report(school_id: str, days: int = 28) -> list:
    """Present counts per day. Paginates so PostgREST's ~1000-row cap can't undercount."""
    today = date.today()
    start = today - timedelta(days=days - 1)
    client = get_client()
    present_by_date: dict[str, int] = defaultdict(int)

    page_size = 1000
    offset = 0
    while True:
        res = (
            await client.table("attendance")
            .select("date")
            .eq("school_id", school_id)
            .eq("status", "present")
            .gte("date", start.isoformat())
            .lte("date", today.isoformat())
            .order("date")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        for row in rows:
            key = row.get("date")
            if key:
                present_by_date[key] += 1
        if len(rows) < page_size:
            break
        offset += page_size

    points = []
    for offset in range(days):
        d = start + timedelta(days=offset)
        key = d.isoformat()
        points.append(
            {
                "date": key,
                "present": present_by_date.get(key, 0),
                "label": str(d.day),
            }
        )
    return points


@router.get("/stats/student-attendance-report")
async def student_attendance_report(
    user: dict = Depends(current_user),
    days: int = 28,
) -> dict:
    days = max(1, min(days, 400))
    school_id = user["school_id"]
    points = await _student_attendance_report(school_id, days=days)
    payload: dict = {"points": points, "days": days}

    # Always include today's summary so Daily gauge works even when
    # the client requests 2+ days for day-over-day comparison.
    total = await _count_students(school_id)
    present = points[-1]["present"] if points else 0
    absent = max(total - present, 0)
    pct = round((present / total) * 100) if total else 0
    payload["summary"] = {
        "total": total,
        "present": present,
        "absent": absent,
        "pct": pct,
    }
    return payload


async def _count_staff(school_id: str) -> int:
    client = get_client()
    res = (
        await client.table("users")
        .select("*", count="exact", head=True)
        .eq("school_id", school_id)
        .in_("role", STAFF_ROLES)
        .execute()
    )
    return res.count if res.count is not None else 0


async def _attendance_pct_today(school_id: str, table: str) -> dict:
    today = date.today().isoformat()
    client = get_client()
    if table == "attendance":
        total = await _count_students(school_id)
        res = (
            await client.table("attendance")
            .select("*", count="exact", head=True)
            .eq("school_id", school_id)
            .eq("date", today)
            .eq("status", "present")
            .execute()
        )
        present = res.count if res.count is not None else 0
    else:
        total = await _count_staff(school_id)
        res = (
            await client.table("staff_attendance")
            .select("*", count="exact", head=True)
            .eq("school_id", school_id)
            .eq("date", today)
            .eq("status", "present")
            .execute()
        )
        present = res.count if res.count is not None else 0
    pct = round((present / total) * 100) if total else 0
    return {"present": present, "total": total, "pct": pct}


async def _today_announcements(school_id: str) -> int:
    today = date.today().isoformat()
    client = get_client()
    res = (
        await client.table("announcements")
        .select("*", count="exact", head=True)
        .eq("school_id", school_id)
        .gte("created_at", f"{today}T00:00:00")
        .execute()
    )
    return res.count if res.count is not None else 0


INCOME_COLOR = "#7E80D5"
EXPENSES_COLOR = "#F87171"
PROFIT_COLOR = "#22C55E"


def _in_period(value: str | None, start: date, end: date) -> bool:
    if not value:
        return False
    day = value[:10]
    return start.isoformat() <= day <= end.isoformat()


def _period_bounds(period: str, month: int | None, year: int | None) -> tuple[date, date, str]:
    today = date.today()
    yr = year or today.year
    if period == "yearly":
        start = date(yr, 1, 1)
        end = date(yr, 12, 31)
        return start, end, str(yr)
    m = max(1, min(12, month or today.month))
    start = date(yr, m, 1)
    end = date(yr, m, calendar.monthrange(yr, m)[1])
    return start, end, f"{start.strftime('%B')} {yr}"


async def _expenses_report(
    school_id: str,
    period: str = "monthly",
    month: int | None = None,
    year: int | None = None,
) -> dict:
    start, end, label = _period_bounds(period, month, year)
    client = get_client()

    payments_res = (
        await client.table("payments")
        .select("amount, paid_at")
        .eq("school_id", school_id)
        .execute()
    )
    fees_res = (
        await client.table("fees")
        .select("amount, status, paid_at, due_date, created_at")
        .eq("school_id", school_id)
        .execute()
    )
    tx_res = (
        await client.table("expense_transactions")
        .select("amount, type, transaction_date")
        .eq("school_id", school_id)
        .execute()
    )

    income = 0.0
    expenses = 0.0

    for row in payments_res.data or []:
        if _in_period(row.get("paid_at"), start, end):
            income += float(row.get("amount") or 0)

    for row in fees_res.data or []:
        amount = float(row.get("amount") or 0)
        ref = row.get("paid_at") or row.get("due_date") or row.get("created_at")
        if not _in_period(ref, start, end):
            continue
        if row.get("status") == "paid":
            income += amount
        else:
            expenses += amount

    for row in tx_res.data or []:
        if not _in_period(row.get("transaction_date"), start, end):
            continue
        amount = float(row.get("amount") or 0)
        if row.get("type") == "income":
            income += amount
        else:
            expenses += amount

    income = round(income, 2)
    expenses = round(expenses, 2)
    profit = round(income - expenses, 2)

    profit_ring = max(profit, 0)
    ring_amounts = [income, expenses, profit_ring]
    ring_total = sum(ring_amounts)
    segments = [
        {"label": "Income", "amount": income, "color": INCOME_COLOR, "pct": 0},
        {"label": "Spending", "amount": expenses, "color": EXPENSES_COLOR, "pct": 0},
        {"label": "Profit", "amount": profit, "color": PROFIT_COLOR, "pct": 0},
    ]
    for seg, ring_val in zip(segments, ring_amounts):
        seg["pct"] = round((ring_val / ring_total) * 100) if ring_total else 0

    return {
        "total": expenses,
        "income": income,
        "expenses": expenses,
        "profit": profit,
        "month_year": label,
        "segments": segments,
    }


@router.get("/stats/expenses-report")
async def expenses_report(
    user: dict = Depends(current_user),
    period: str = "monthly",
    month: int | None = None,
    year: int | None = None,
) -> dict:
    view = "yearly" if period == "yearly" else "monthly"
    return await _expenses_report(user["school_id"], view, month, year)


@router.get("/stats/live-activity", response_model=list[SchoolActivityOut])
async def live_activity(
    user: dict = Depends(current_user),
    limit: int = 10,
) -> list[SchoolActivityOut]:
    capped = max(1, min(limit, 50))
    rows = await school_activity_service.list_school_live_activity(user["school_id"], limit=capped)
    return [SchoolActivityOut(**row) for row in rows]


@router.get("/stats")
async def stats(user: dict = Depends(current_user)) -> dict:
    s = user["school_id"]
    (
        students,
        total_staff,
        pending_fees,
        announcements,
        student_att,
        staff_att,
        today_ann,
    ) = await asyncio.gather(
        _count_students(s),
        _count_staff(s),
        _sum_pending_fees(s),
        _count("announcements", s),
        _attendance_pct_today(s, "attendance"),
        _attendance_pct_today(s, "staff_attendance"),
        _today_announcements(s),
    )
    return {
        "students": students,
        "total_staff": total_staff,
        "teachers": await _count("users", s, role="teacher"),
        "pending_fees": pending_fees,
        "announcements": announcements,
        "today_announcements": today_ann,
        "student_attendance_today": student_att,
        "staff_attendance_today": staff_att,
        # legacy fields for backward compatibility
        "users": students + total_staff,
        "parents": await _count("users", s, role="parent"),
        "homework": await _count("homework", s),
    }
