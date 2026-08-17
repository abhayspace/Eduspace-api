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
            .select("section_id,class_id,monthly_amount")
            .eq("school_id", school_id)
            .execute(),
        )
    except APIError as exc:
        _raise_if_missing_fees_table(exc)

    amount_by_section = {
        row["section_id"]: float(row["monthly_amount"])
        for row in (fees_res.data or [])
        if row.get("section_id") is not None
    }

    result: List[FeeStructureClassOut] = []
    for row in classes_res.data or []:
        sections_raw = row.get("sections") or []
        sections: List[FeeStructureSectionOut] = []
        amounts: List[float] = []
        for sec in sections_raw:
            amt = amount_by_section.get(sec["id"])
            if amt is not None:
                amounts.append(amt)
            sections.append(
                FeeStructureSectionOut(
                    id=sec["id"],
                    name=sec["name"],
                    monthly_amount=amt,
                )
            )
        class_amount: Optional[float] = None
        if amounts and len(set(amounts)) == 1:
            class_amount = amounts[0]
        result.append(
            FeeStructureClassOut(
                id=row["id"],
                name=row["name"],
                monthly_amount=class_amount,
                sections=sections,
            )
        )
    return result


async def _upsert_section_amount(
    school_id: str,
    class_id: str,
    section_id: str,
    amount: float,
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
        "updated_at": now,
    }
    try:
        if existing.data:
            await (
                client.table("class_section_fees")
                .update({"monthly_amount": amount, "updated_at": now, "class_id": class_id})
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
    month_start = f"{month_prefix}-01T00:00:00+00:00"
    last_day = monthrange(today.year, today.month)[1]
    month_end = f"{month_prefix}-{last_day:02d}T23:59:59.999999+00:00"

    page_size = 1000

    async def _fetch_pending_fees() -> tuple[float, set[str]]:
        """Fetch only pending fees — reduces payload vs fetching all fees."""
        total = 0.0
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
                    total += float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
                due = str(row.get("due_date") or "")
                title = str(row.get("title") or "").lower()
                if due.startswith(month_prefix) or month_label in title:
                    email = (row.get("student_email") or "").strip().lower()
                    if email:
                        emails.add(email)
            if len(rows) < page_size:
                break
            offset += page_size
        return total, emails

    async def _fetch_payments() -> float:
        """Fetch payments for the current month."""
        total = 0.0
        offset = 0
        while True:
            pay_res = (
                await client.table("payments")
                .select("amount,paid_at")
                .eq("school_id", school_id)
                .gte("paid_at", month_start)
                .lte("paid_at", month_end)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            pay_rows = pay_res.data or []
            for row in pay_rows:
                try:
                    total += float(row.get("amount") or 0)
                except (TypeError, ValueError):
                    continue
            if len(pay_rows) < page_size:
                break
            offset += page_size
        return total

    pending_total, unpaid_emails = await _fetch_pending_fees()
    paid_this_month = await _fetch_payments()

    # Fallback if payments table empty but fees were marked paid without ledger rows
    if paid_this_month <= 0:
        fee_paid = 0.0
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
                in_month = False
                if ref:
                    if ref.startswith(month_prefix):
                        in_month = True
                    else:
                        try:
                            dt = datetime.fromisoformat(ref.replace("Z", "+00:00"))
                            in_month = dt.year == today.year and dt.month == today.month
                        except Exception:
                            in_month = len(ref) >= 7 and ref[:7] == month_prefix
                if in_month:
                    try:
                        fee_paid += float(row.get("amount") or 0)
                    except (TypeError, ValueError):
                        pass
            if len(rows) < page_size:
                break
            offset += page_size
        paid_this_month = fee_paid

    return {
        "total_due": round(pending_total, 2),
        "paid_this_month": round(paid_this_month, 2),
        "unpaid_students_this_month": len(unpaid_emails),
        "retention_months": FEE_RETENTION_MONTHS,
    }


async def set_class_monthly_amount(school_id: str, class_id: str, amount: float) -> FeeStructureClassOut:
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
        await _upsert_section_amount(school_id, class_id, sec["id"], amount)
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
    school_id: str, section_id: str, amount: float
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

    await _upsert_section_amount(school_id, class_id, section_id, amount)
    await _apply_monthly_fees_for_sections(
        school_id,
        class_id,
        class_name,
        {section_id: amount},
        overwrite_pending_amount=True,
    )
    return FeeStructureSectionOut(id=section_id, name=row["name"], monthly_amount=amount)
