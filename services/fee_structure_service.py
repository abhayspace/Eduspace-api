"""Class/section monthly fee structure + student fee generation."""
from __future__ import annotations

import asyncio
from calendar import monthrange
from datetime import date, datetime, timezone
from typing import Iterable, List, Optional

from fastapi import HTTPException, status
from postgrest.exceptions import APIError

from database import get_client
from schemas.content import FeeStructureClassOut, FeeStructureSectionOut

# Keep fee history (paid rows) for this many months; pending dues are never purged.
FEE_RETENTION_MONTHS = 18


def months_ago_date(months: int, *, today: Optional[date] = None) -> date:
    """First day of the month `months` before today."""
    today = today or date.today()
    year, month = today.year, today.month - months
    while month <= 0:
        month += 12
        year -= 1
    return date(year, month, 1)


def _missing_table_error(exc: APIError) -> bool:
    if getattr(exc, "code", None) == "PGRST205":
        return True
    payload = exc.args[0] if exc.args else {}
    if isinstance(payload, dict):
        return payload.get("code") == "PGRST205"
    return False


def _raise_if_missing_fees_table(exc: APIError) -> None:
    if _missing_table_error(exc):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Database table 'class_section_fees' is missing. "
                "Run backend/migrations/035_class_section_fees.sql in Supabase SQL Editor, "
                "or set DATABASE_URL in backend/.env and run: python migrate.py"
            ),
        ) from exc
    raise exc


def _month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%b %Y")


def _fee_title(class_name: str, year: int, month: int) -> str:
    return f"{class_name} · Monthly fee · {_month_label(year, month)}"


def _due_date(year: int, month: int) -> str:
    last = monthrange(year, month)[1]
    return f"{year:04d}-{month:02d}-{last:02d}"


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def ensure_current_month_fees(school_id: str) -> int:
    """Apply scheduled section fees to all students for the current month."""
    from utils.ttl_cache import should_run

    if not should_run(f"ensure_monthly_fees:{school_id}", ttl_seconds=600):
        return 0
    await purge_old_paid_fees(school_id)
    client = get_client()
    try:
        fees_res = (
            await client.table("class_section_fees")
            .select("section_id,class_id,monthly_amount")
            .eq("school_id", school_id)
            .execute()
        )
    except APIError as exc:
        _raise_if_missing_fees_table(exc)

    rows = fees_res.data or []
    if not rows:
        return 0

    by_class: dict[str, dict[str, float]] = {}
    for row in rows:
        class_id = row.get("class_id")
        section_id = row.get("section_id")
        if not class_id or not section_id:
            continue
        by_class.setdefault(class_id, {})[section_id] = float(row["monthly_amount"])

    class_ids = list(by_class.keys())
    names: dict[str, str] = {}
    if class_ids:
        cls_res = (
            await client.table("classes")
            .select("id,name")
            .eq("school_id", school_id)
            .in_("id", class_ids)
            .execute()
        )
        for c in cls_res.data or []:
            names[c["id"]] = c["name"]

    touched = 0
    for class_id, section_amounts in by_class.items():
        class_name = names.get(class_id) or "Class"
        touched += await _apply_monthly_fees_for_sections(
            school_id, class_id, class_name, section_amounts
        )

    # Custom class charges scheduled for this month (annual fee, caution…).
    today = date.today()
    try:
        touched += await apply_month_charges(school_id, today.year, today.month)
    except Exception:
        pass
    return touched


async def purge_old_paid_fees(school_id: str) -> int:
    """Drop paid fee rows older than FEE_RETENTION_MONTHS. Pending dues are kept."""
    from utils.ttl_cache import should_run

    if not should_run(f"purge_fees:{school_id}", ttl_seconds=600):
        return 0
    client = get_client()
    cutoff = months_ago_date(FEE_RETENTION_MONTHS).isoformat()
    deleted = 0
    try:
        # Paid fees whose due month is outside the retention window
        old = (
            await client.table("fees")
            .select("id")
            .eq("school_id", school_id)
            .eq("status", "paid")
            .lt("due_date", cutoff)
            .limit(500)
            .execute()
        )
        ids = [row["id"] for row in (old.data or []) if row.get("id")]
        if ids:
            await (
                client.table("fees")
                .delete()
                .eq("school_id", school_id)
                .eq("status", "paid")
                .in_("id", ids)
                .execute()
            )
            deleted = len(ids)
        # Old payment ledger rows
        await (
            client.table("payments")
            .delete()
            .eq("school_id", school_id)
            .lt("paid_at", cutoff)
            .execute()
        )
    except Exception:
        pass
    return deleted


async def list_fee_structure(school_id: str) -> List[FeeStructureClassOut]:
    await ensure_current_month_fees(school_id)
    client = get_client()

    try:
        classes_res, fees_res = await asyncio.gather(
            client.table("classes")
            .select("id,name,sections(id,name)")
            .eq("school_id", school_id)
            .order("name")
            .execute(),
            client.table("class_section_fees")
            .select("section_id,class_id,monthly_amount,breakdown")
            .eq("school_id", school_id)
            .execute(),
        )
    except APIError as exc:
        _raise_if_missing_fees_table(exc)

    amount_by_section: dict[str, float] = {}
    breakdown_by_section: dict[str, list] = {}
    for row in fees_res.data or []:
        sid = row.get("section_id")
        if sid is None:
            continue
        amount_by_section[sid] = float(row["monthly_amount"])
        if row.get("breakdown"):
            breakdown_by_section[sid] = row["breakdown"]

    result: List[FeeStructureClassOut] = []
    for row in classes_res.data or []:
        sections_raw = row.get("sections") or []
        sections: List[FeeStructureSectionOut] = []
        amounts: List[float] = []
        breakdowns: List[list] = []
        for sec in sections_raw:
            amt = amount_by_section.get(sec["id"])
            bd = breakdown_by_section.get(sec["id"])
            if amt is not None:
                amounts.append(amt)
            if bd:
                breakdowns.append(bd)
            sections.append(
                FeeStructureSectionOut(
                    id=sec["id"],
                    name=sec["name"],
                    monthly_amount=amt,
                    breakdown=bd,
                )
            )
        class_amount: Optional[float] = None
        class_breakdown: Optional[list] = None
        if amounts and len(set(amounts)) == 1:
            class_amount = amounts[0]
            if len(breakdowns) == len(amounts) and len({str(b) for b in breakdowns}) == 1:
                class_breakdown = breakdowns[0]
        result.append(
            FeeStructureClassOut(
                id=row["id"],
                name=row["name"],
                monthly_amount=class_amount,
                breakdown=class_breakdown,
                sections=sections,
            )
        )
    return result


async def _upsert_section_amount(
    school_id: str,
    class_id: str,
    section_id: str,
    amount: float,
    breakdown: Optional[list] = None,
) -> None:
    client = get_client()
    now = _now().isoformat()
    existing = (
        await client.table("class_section_fees")
        .select("id")
        .eq("school_id", school_id)
        .eq("section_id", section_id)
        .limit(1)
        .execute()
    )
    payload = {
        "school_id": school_id,
        "class_id": class_id,
        "section_id": section_id,
        "monthly_amount": amount,
        "breakdown": breakdown,
        "updated_at": now,
    }
    try:
        if existing.data:
            await (
                client.table("class_section_fees")
                .update(
                    {
                        "monthly_amount": amount,
                        "breakdown": breakdown,
                        "updated_at": now,
                        "class_id": class_id,
                    }
                )
                .eq("id", existing.data[0]["id"])
                .execute()
            )
        else:
            payload["created_at"] = now
            await client.table("class_section_fees").insert(payload).execute()
    except APIError as exc:
        _raise_if_missing_fees_table(exc)


async def _student_emails_for_sections(
    school_id: str, section_ids: Iterable[str]
) -> dict[str, list[str]]:
    """Map section_id -> list of student emails."""
    ids = [sid for sid in section_ids if sid]
    if not ids:
        return {}
    client = get_client()
    students_res = (
        await client.table("students")
        .select("section_id,user_id")
        .eq("school_id", school_id)
        .in_("section_id", ids)
        .execute()
    )
    rows = students_res.data or []
    user_ids = [r["user_id"] for r in rows if r.get("user_id")]
    email_by_user: dict[str, str] = {}
    if user_ids:
        users_res = (
            await client.table("users")
            .select("id,email")
            .eq("school_id", school_id)
            .in_("id", user_ids)
            .execute()
        )
        for u in users_res.data or []:
            if u.get("email"):
                email_by_user[u["id"]] = u["email"]

    out: dict[str, list[str]] = {sid: [] for sid in ids}
    for row in rows:
        sid = row.get("section_id")
        uid = row.get("user_id")
        email = email_by_user.get(uid) if uid else None
        if sid and email:
            out.setdefault(sid, []).append(email)
    return out


async def _apply_monthly_fees_for_sections(
    school_id: str,
    class_id: str,
    class_name: str,
    section_amounts: dict[str, float],
    *,
    year: Optional[int] = None,
    month: Optional[int] = None,
    overwrite_pending_amount: bool = False,
) -> int:
    """Create monthly fee rows for students.

    Existing paid rows are never touched. Existing pending rows keep their
    current amount unless overwrite_pending_amount=True (admin fee set).
    """
    if not section_amounts:
        return 0
    today = date.today()
    year = year or today.year
    month = month or today.month
    title = _fee_title(class_name, year, month)
    due = _due_date(year, month)
    client = get_client()

    emails_by_section = await _student_emails_for_sections(school_id, section_amounts.keys())

    # Collect all emails across sections for batch existence check
    all_emails: list[str] = []
    for emails in emails_by_section.values():
        all_emails.extend(emails)
    if not all_emails:
        return 0

    # Batch check: fetch all existing fees for these emails + title in one query
    existing_res = (
        await client.table("fees")
        .select("id,student_email,status,amount")
        .eq("school_id", school_id)
        .eq("title", title)
        .in_("student_email", all_emails)
        .execute()
    )
    existing_map: dict[str, dict] = {}
    for row in (existing_res.data or []):
        existing_map[row["student_email"]] = row

    touched = 0
    to_insert: list[dict] = []
    for section_id, amount in section_amounts.items():
        if float(amount) <= 0:
            continue
        emails = emails_by_section.get(section_id) or []
        for email in emails:
            existing = existing_map.get(email)
            if existing:
                if existing.get("status") != "pending":
                    continue
                if overwrite_pending_amount and float(existing.get("amount") or 0) != float(amount):
                    await (
                        client.table("fees")
                        .update({"amount": amount, "due_date": due})
                        .eq("id", existing["id"])
                        .execute()
                    )
                    touched += 1
                continue
            to_insert.append(
                {
                    "school_id": school_id,
                    "student_email": email,
                    "title": title,
                    "amount": amount,
                    "due_date": due,
                    "status": "pending",
                }
            )
            touched += 1

    # Batch insert all new fees in one query
    if to_insert:
        try:
            await client.table("fees").insert(to_insert).execute()
        except Exception:
            pass
    return touched


async def sum_pending_fees(school_id: str, *, ensure_monthly: bool = True) -> float:
    """Outstanding dues only — paid fees are excluded."""
    if ensure_monthly:
        try:
            await ensure_current_month_fees(school_id)
        except Exception:
            pass

    client = get_client()
    total = 0.0
    page_size = 1000
    offset = 0
    while True:
        res = (
            await client.table("fees")
            .select("amount")
            .eq("school_id", school_id)
            .eq("status", "pending")
            .range(offset, offset + page_size - 1)
            .execute()
        )
        rows = res.data or []
        for row in rows:
            try:
                total += float(row.get("amount") or 0)
            except (TypeError, ValueError):
                continue
        if len(rows) < page_size:
            break
        offset += page_size
    return round(total, 2)


async def school_fee_dashboard_stats(school_id: str) -> dict:
    """Shared totals for home Fees Due + fees page Total Due."""
    from datetime import datetime

    try:
        await ensure_current_month_fees(school_id)
    except Exception:
        pass

    client = get_client()
    today = date.today()
    month_prefix = f"{today.year:04d}-{today.month:02d}"
    month_label = today.strftime("%b %Y").lower()

    page_size = 1000

    async def _fetch_pending_fees() -> tuple[float, float, int, set[str]]:
        """Fetch only pending fees — reduces payload vs fetching all fees."""
        total = 0.0
        overdue = 0.0
        pending_count = 0
        today_iso = today.isoformat()
        emails: set[str] = set()
        offset = 0
        while True:
            res = (
                await client.table("fees")
                .select("amount,due_date,student_email,title")
                .eq("school_id", school_id)
                .eq("status", "pending")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = res.data or []
            for row in rows:
                try:
                    amt = float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                if amt <= 0:
                    continue
                total += amt
                pending_count += 1
                due = str(row.get("due_date") or "")
                if due and due < today_iso:
                    overdue += amt
                title = str(row.get("title") or "").lower()
                if due.startswith(month_prefix) or month_label in title:
                    email = (row.get("student_email") or "").strip().lower()
                    if email:
                        emails.add(email)
            if len(rows) < page_size:
                break
            offset += page_size
        return total, overdue, pending_count, emails

    async def _fetch_year_payments() -> list[float]:
        """Payments collected per month for the current calendar year."""
        monthly = [0.0] * 12
        year_start = f"{today.year:04d}-01-01T00:00:00+00:00"
        year_end = f"{today.year:04d}-12-31T23:59:59.999999+00:00"
        offset = 0
        while True:
            pay_res = (
                await client.table("payments")
                .select("amount,paid_at")
                .eq("school_id", school_id)
                .gte("paid_at", year_start)
                .lte("paid_at", year_end)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            pay_rows = pay_res.data or []
            for row in pay_rows:
                try:
                    amt = float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                ref = str(row.get("paid_at") or "")
                try:
                    mi = int(ref[5:7]) - 1
                except (TypeError, ValueError):
                    continue
                if 0 <= mi <= 11:
                    monthly[mi] += amt
            if len(pay_rows) < page_size:
                break
            offset += page_size
        return monthly

    async def _fetch_year_fees_paid() -> list[float]:
        """Fallback: paid fee rows bucketed per month (when payments ledger is empty)."""
        monthly = [0.0] * 12
        offset = 0
        while True:
            res = (
                await client.table("fees")
                .select("amount,status,paid_at,due_date")
                .eq("school_id", school_id)
                .eq("status", "paid")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = res.data or []
            for row in rows:
                paid_at = str(row.get("paid_at") or "")
                due = str(row.get("due_date") or "")
                ref = paid_at or due
                if not ref:
                    continue
                in_year = False
                if ref.startswith(f"{today.year:04d}-"):
                    in_year = True
                else:
                    try:
                        dt = datetime.fromisoformat(ref.replace("Z", "+00:00"))
                        in_year = dt.year == today.year
                    except Exception:
                        in_year = len(ref) >= 4 and ref[:4] == f"{today.year:04d}"
                if not in_year:
                    continue
                try:
                    mi = int(ref[5:7]) - 1
                except (TypeError, ValueError):
                    continue
                if not (0 <= mi <= 11):
                    continue
                try:
                    monthly[mi] += float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    pass
            if len(rows) < page_size:
                break
            offset += page_size
        return monthly

    pending_total, overdue_total, pending_count, unpaid_emails = await _fetch_pending_fees()
    monthly_collected = await _fetch_year_payments()
    paid_this_month = monthly_collected[today.month - 1]

    # Fallback if payments ledger is empty but fees were marked paid without rows
    if sum(monthly_collected) <= 0:
        fallback_monthly = await _fetch_year_fees_paid()
        if sum(fallback_monthly) > 0:
            monthly_collected = fallback_monthly
            paid_this_month = monthly_collected[today.month - 1]

    return {
        "total_due": round(pending_total, 2),
        "overdue_due": round(overdue_total, 2),
        "pending_count": pending_count,
        "paid_this_month": round(paid_this_month, 2),
        "monthly_collected": [round(m, 2) for m in monthly_collected],
        "unpaid_students_this_month": len(unpaid_emails),
        "retention_months": FEE_RETENTION_MONTHS,
    }


async def set_class_monthly_amount(
    school_id: str, class_id: str, amount: float, breakdown: Optional[list] = None
) -> FeeStructureClassOut:
    client = get_client()
    cls = (
        await client.table("classes")
        .select("id,name,sections(id,name)")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    if not cls.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class not found")
    class_row = cls.data[0]
    sections = class_row.get("sections") or []
    if not sections:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Class has no sections")

    section_amounts: dict[str, float] = {}
    for sec in sections:
        await _upsert_section_amount(school_id, class_id, sec["id"], amount, breakdown)
        section_amounts[sec["id"]] = amount

    await _apply_monthly_fees_for_sections(
        school_id,
        class_id,
        class_row["name"],
        section_amounts,
        overwrite_pending_amount=True,
    )

    structure = await list_fee_structure(school_id)
    for item in structure:
        if item.id == class_id:
            return item
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to load fee structure")


async def set_section_monthly_amount(
    school_id: str, section_id: str, amount: float, breakdown: Optional[list] = None
) -> FeeStructureSectionOut:
    client = get_client()
    sec = (
        await client.table("sections")
        .select("id,name,class_id,classes(id,name)")
        .eq("school_id", school_id)
        .eq("id", section_id)
        .limit(1)
        .execute()
    )
    if not sec.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Section not found")
    row = sec.data[0]
    class_id = row["class_id"]
    class_info = row.get("classes") or {}
    class_name = class_info.get("name") if isinstance(class_info, dict) else None
    if not class_name:
        cls = (
            await client.table("classes")
            .select("name")
            .eq("id", class_id)
            .eq("school_id", school_id)
            .limit(1)
            .execute()
        )
        class_name = (cls.data or [{}])[0].get("name") or "Class"

    await _upsert_section_amount(school_id, class_id, section_id, amount, breakdown)
    await _apply_monthly_fees_for_sections(
        school_id,
        class_id,
        class_name,
        {section_id: amount},
        overwrite_pending_amount=True,
    )
    return FeeStructureSectionOut(
        id=section_id, name=row["name"], monthly_amount=amount, breakdown=breakdown
    )


# ---------------------------------------------------------------------------
# Custom class charges (annual fee, caution money, …) applied in a given month
# ---------------------------------------------------------------------------


async def list_class_charges(
    school_id: str, class_id: Optional[str] = None
) -> List[dict]:
    client = get_client()
    q = (
        client.table("class_fee_charges")
        .select("id,class_id,title,amount,apply_month,created_at")
        .eq("school_id", school_id)
    )
    if class_id:
        q = q.eq("class_id", class_id)
    res = await q.order("apply_month").execute()
    rows = res.data or []
    class_ids = {r["class_id"] for r in rows if r.get("class_id")}
    names: dict[str, str] = {}
    if class_ids:
        cls_res = (
            await client.table("classes")
            .select("id,name")
            .eq("school_id", school_id)
            .in_("id", list(class_ids))
            .execute()
        )
        for c in cls_res.data or []:
            names[c["id"]] = c.get("name") or ""
    return [
        {**r, "class_name": names.get(r.get("class_id") or "", "")}
        for r in rows
    ]


async def _apply_class_charge(
    school_id: str, charge: dict, *, year: Optional[int] = None
) -> int:
    """Create pending fee rows for every student of the charge's class.

    Title carries the month+year so the same charge can recur every year and
    existing rows (paid or pending) are never duplicated.
    """
    client = get_client()
    class_id = charge.get("class_id")
    month = int(charge.get("apply_month") or 0)
    amount = float(charge.get("amount") or 0)
    if not class_id or not (1 <= month <= 12) or amount <= 0:
        return 0
    year = year or date.today().year

    cls_res = (
        await client.table("classes")
        .select("sections(id)")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    sections = (cls_res.data or [{}])[0].get("sections") or []
    emails_by_section = await _student_emails_for_sections(
        school_id, [s["id"] for s in sections if s.get("id")]
    )
    all_emails = sorted({e for v in emails_by_section.values() for e in v})
    if not all_emails:
        return 0

    title = f"{charge.get('title')} · {_month_label(year, month)}"
    due = _due_date(year, month)

    existing_res = (
        await client.table("fees")
        .select("student_email")
        .eq("school_id", school_id)
        .eq("title", title)
        .in_("student_email", all_emails)
        .execute()
    )
    existing = {r["student_email"] for r in (existing_res.data or [])}

    to_insert = [
        {
            "school_id": school_id,
            "student_email": email,
            "title": title,
            "amount": amount,
            "due_date": due,
            "status": "pending",
        }
        for email in all_emails
        if email not in existing
    ]
    if to_insert:
        try:
            await client.table("fees").insert(to_insert).execute()
        except Exception:
            return 0
    return len(to_insert)


async def apply_month_charges(school_id: str, year: int, month: int) -> int:
    """Apply every class charge scheduled for `month` of `year`."""
    client = get_client()
    try:
        res = (
            await client.table("class_fee_charges")
            .select("id,class_id,title,amount,apply_month")
            .eq("school_id", school_id)
            .eq("apply_month", month)
            .execute()
        )
    except APIError:
        return 0  # table may not exist yet (migration pending)
    touched = 0
    for charge in res.data or []:
        try:
            touched += await _apply_class_charge(school_id, charge, year=year)
        except Exception:
            continue
    return touched


async def add_class_charges(
    school_id: str,
    class_ids: List[str],
    title: str,
    amount: float,
    apply_months: List[int],
) -> List[dict]:
    """Create charge rows for every (class, month) combination.

    Empty ``class_ids`` means "all classes" of the school.
    """
    title = title.strip()
    if not title:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Charge title is required")
    if amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Enter a valid amount")
    months = sorted({int(m) for m in apply_months if 1 <= int(m) <= 12})
    if not months:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Pick at least one month")

    client = get_client()
    cls_res = (
        await client.table("classes")
        .select("id,name")
        .eq("school_id", school_id)
        .execute()
    )
    all_classes = cls_res.data or []
    if class_ids:
        wanted = set(class_ids)
        targets = [c for c in all_classes if c["id"] in wanted]
    else:
        targets = all_classes
    if not targets:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No matching classes found")

    # Skip combos that already exist so retries never double-create charges.
    existing_res = (
        await client.table("class_fee_charges")
        .select("class_id,apply_month")
        .eq("school_id", school_id)
        .eq("title", title)
        .eq("amount", amount)
        .in_("class_id", [c["id"] for c in targets])
        .execute()
    )
    existing = {
        (r["class_id"], int(r["apply_month"])) for r in (existing_res.data or [])
    }

    rows_payload = [
        {
            "school_id": school_id,
            "class_id": c["id"],
            "title": title,
            "amount": amount,
            "apply_month": month,
        }
        for c in targets
        for month in months
        if (c["id"], month) not in existing
    ]
    if not rows_payload:
        return []
    res = await client.table("class_fee_charges").insert(rows_payload).execute()
    rows = res.data or []
    name_by_id = {c["id"]: c.get("name") or "" for c in targets}
    for r in rows:
        r["class_name"] = name_by_id.get(r.get("class_id") or "", "")

    # Bill students immediately for combos scheduled in the current month.
    today = date.today()
    for row in rows:
        if int(row.get("apply_month") or 0) == today.month:
            try:
                await _apply_class_charge(school_id, row, year=today.year)
            except Exception:
                pass
    return rows


async def delete_class_charge(school_id: str, charge_id: str) -> None:
    client = get_client()
    await (
        client.table("class_fee_charges")
        .delete()
        .eq("school_id", school_id)
        .eq("id", charge_id)
        .execute()
    )
