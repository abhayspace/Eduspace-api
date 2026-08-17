"""Expense / income transactions per school."""
from __future__ import annotations

import asyncio
import calendar
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

from fastapi import HTTPException, status

from database import get_client
from schemas.content import (
    ExpenseTransactionCreateIn,
    ExpenseTransactionOut,
    ExpenseTransactionUpdateIn,
    SavingCreateIn,
    SavingOut,
    SavingUpdateIn,
)

_VALID_TYPES = frozenset({"income", "expense"})
_COLUMNS = "id,title,amount,type,transaction_date,created_at"
TRANSACTION_RETENTION_DAYS = 365


def transaction_retention_start(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=TRANSACTION_RETENTION_DAYS - 1)


def _month_bounds(month: int, year: int) -> Tuple[str, str]:
    m = max(1, min(12, month))
    y = max(1970, year)
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    return start.isoformat(), end.isoformat()


def ensure_transaction_date_allowed(value: str | None, today: date | None = None) -> str:
    parsed = date.fromisoformat(_parse_date(value))
    anchor = today or date.today()
    if parsed > anchor:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Transaction date cannot be in the future")
    if parsed < transaction_retention_start(anchor):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Transactions are only kept for the last {TRANSACTION_RETENTION_DAYS} days",
        )
    return parsed.isoformat()


def _parse_date(value: str | None) -> str:
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid transaction date") from exc


def _parse_dt(value) -> datetime:
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(value, datetime):
        return value
    return datetime.now(timezone.utc)


def _to_tx_date(value) -> str:
    if hasattr(value, "isoformat") and hasattr(value, "year") and not hasattr(value, "hour"):
        return value.isoformat()
    if hasattr(value, "date"):
        return value.date().isoformat()
    if isinstance(value, str):
        return value[:10]
    return date.today().isoformat()


async def _purge_expired_transactions(school_id: str, today: date | None = None) -> None:
    from utils.ttl_cache import should_run

    if not should_run(f"purge_transactions:{school_id}", ttl_seconds=300):
        return
    cutoff = transaction_retention_start(today or date.today()).isoformat()
    client = get_client()
    await (
        client.table("expense_transactions")
        .delete()
        .eq("school_id", school_id)
        .lt("transaction_date", cutoff)
        .execute()
    )


async def list_recent_transactions(
    school_id: str,
    limit: int = 30,
    month: Optional[int] = None,
    year: Optional[int] = None,
    on_date: Optional[str] = None,
) -> List[ExpenseTransactionOut]:
    await _purge_expired_transactions(school_id)
    retention_cutoff = transaction_retention_start().isoformat()

    if on_date is not None:
        day = ensure_transaction_date_allowed(on_date)
        return await _list_transactions_merged(
            school_id,
            from_date=day,
            to_date=day,
        )

    if month is not None and year is not None:
        month_start, month_end = _month_bounds(month, year)
        if month_end < retention_cutoff:
            return []
        range_start = max(month_start, retention_cutoff)
        return await _list_transactions_merged(
            school_id,
            from_date=range_start,
            to_date=month_end,
        )

    fetch_cap = max(limit, min(limit * 3, 500))
    merged = await _list_transactions_merged(
        school_id,
        from_date=retention_cutoff,
        to_date=None,
        fetch_cap=fetch_cap,
    )
    return merged[:limit]


async def _list_transactions_merged(
    school_id: str,
    from_date: str,
    to_date: str | None,
    fetch_cap: int = 5000,
) -> List[ExpenseTransactionOut]:
    client = get_client()

    tx_query = (
        client.table("expense_transactions")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .gte("transaction_date", from_date)
    )
    if to_date:
        tx_query = tx_query.lte("transaction_date", to_date)
    tx_query = tx_query.order("transaction_date", desc=True).order("created_at", desc=True).limit(fetch_cap)

    pay_query = (
        client.table("payments")
        .select("id, amount, paid_at, fee_id")
        .eq("school_id", school_id)
        .gte("paid_at", f"{from_date}T00:00:00")
    )
    if to_date:
        pay_query = pay_query.lte("paid_at", f"{to_date}T23:59:59")
    pay_query = pay_query.order("paid_at", desc=True).limit(fetch_cap)

    tx_res, pay_res = await asyncio.gather(tx_query.execute(), pay_query.execute())
    manual = [_row_to_out(row) for row in (tx_res.data or [])]
    payments = pay_res.data or []
    fee_ids = [row.get("fee_id") for row in payments if row.get("fee_id")]
    fee_titles: dict[str, str] = {}
    if fee_ids:
        fees_res = (
            await client.table("fees")
            .select("id, title")
            .eq("school_id", school_id)
            .in_("id", fee_ids)
            .execute()
        )
        fee_titles = {row["id"]: row.get("title") or "Student fee" for row in (fees_res.data or [])}

    fee_rows: List[ExpenseTransactionOut] = []
    for row in payments:
        fee_id = row.get("fee_id")
        fee_title = fee_titles.get(fee_id, "Student fee") if fee_id else "Student fee"
        paid_at = row.get("paid_at")
        fee_rows.append(
            ExpenseTransactionOut(
                id=row["id"],
                title=f"Fee · {fee_title}",
                amount=float(row.get("amount") or 0),
                type="income",
                transaction_date=_to_tx_date(paid_at),
                created_at=_parse_dt(paid_at),
                source="fee",
            )
        )

    merged = sorted(
        manual + fee_rows,
        key=lambda item: (item.transaction_date, item.created_at),
        reverse=True,
    )
    return merged


async def create_transaction(
    school_id: str,
    body: ExpenseTransactionCreateIn,
    created_by: str,
) -> ExpenseTransactionOut:
    if body.type not in _VALID_TYPES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid transaction type")
    if body.amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be greater than zero")
    if not body.title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Title is required")

    client = get_client()
    tx_date = ensure_transaction_date_allowed(body.transaction_date)
    inserted = (
        await client.table("expense_transactions")
        .insert(
            {
                "school_id": school_id,
                "title": body.title.strip(),
                "amount": round(float(body.amount), 2),
                "type": body.type,
                "transaction_date": tx_date,
                "notes": body.notes,
                "created_by": created_by,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create transaction")
    await _purge_expired_transactions(school_id)
    return _row_to_out(inserted.data[0])


async def update_transaction(
    school_id: str,
    transaction_id: str,
    body: ExpenseTransactionUpdateIn,
) -> ExpenseTransactionOut:
    client = get_client()
    existing = (
        await client.table("expense_transactions")
        .select(_COLUMNS)
        .eq("id", transaction_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")

    patch: dict = {}
    if body.title is not None:
        trimmed = body.title.strip()
        if not trimmed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Title is required")
        patch["title"] = trimmed
    if body.amount is not None:
        if body.amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be greater than zero")
        patch["amount"] = round(float(body.amount), 2)
    if body.type is not None:
        if body.type not in _VALID_TYPES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid transaction type")
        patch["type"] = body.type
    if body.transaction_date is not None:
        patch["transaction_date"] = ensure_transaction_date_allowed(body.transaction_date)

    if not patch:
        return _row_to_out(existing.data[0])

    updated = (
        await client.table("expense_transactions")
        .update(patch)
        .eq("id", transaction_id)
        .eq("school_id", school_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update transaction")
    return _row_to_out(updated.data[0])


async def delete_transaction(school_id: str, transaction_id: str) -> None:
    client = get_client()
    existing = (
        await client.table("expense_transactions")
        .select("id")
        .eq("id", transaction_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    await (
        client.table("expense_transactions")
        .delete()
        .eq("id", transaction_id)
        .eq("school_id", school_id)
        .execute()
    )


_SAVING_COLUMNS = "id,title,amount,saved_date,sort_order,created_at"


async def list_savings(school_id: str) -> List[SavingOut]:
    client = get_client()
    res = (
        await client.table("expense_savings")
        .select(_SAVING_COLUMNS)
        .eq("school_id", school_id)
        .order("sort_order", desc=False)
        .order("saved_date", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return [_saving_row_to_out(row) for row in (res.data or [])]


async def create_saving(
    school_id: str,
    body: SavingCreateIn,
    created_by: str,
) -> SavingOut:
    if body.amount <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be greater than zero")
    if not body.title.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Title is required")

    client = get_client()
    next_order_res = (
        await client.table("expense_savings")
        .select("sort_order")
        .eq("school_id", school_id)
        .order("sort_order", desc=True)
        .limit(1)
        .execute()
    )
    next_order = 0
    if next_order_res.data:
        next_order = int(next_order_res.data[0].get("sort_order") or 0) + 1

    inserted = (
        await client.table("expense_savings")
        .insert(
            {
                "school_id": school_id,
                "title": body.title.strip(),
                "amount": round(float(body.amount), 2),
                "saved_date": _parse_date(body.saved_date),
                "sort_order": next_order,
                "created_by": created_by,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create saving")
    return _saving_row_to_out(inserted.data[0])


async def update_saving(
    school_id: str,
    saving_id: str,
    body: SavingUpdateIn,
) -> SavingOut:
    client = get_client()
    existing = (
        await client.table("expense_savings")
        .select(_SAVING_COLUMNS)
        .eq("id", saving_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saving not found")

    patch: dict = {}
    if body.title is not None:
        trimmed = body.title.strip()
        if not trimmed:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Title is required")
        patch["title"] = trimmed
    if body.amount is not None:
        if body.amount <= 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount must be greater than zero")
        patch["amount"] = round(float(body.amount), 2)
    if body.saved_date is not None:
        patch["saved_date"] = _parse_date(body.saved_date)
    if body.sort_order is not None:
        patch["sort_order"] = int(body.sort_order)

    if not patch:
        return _saving_row_to_out(existing.data[0])

    updated = (
        await client.table("expense_savings")
        .update(patch)
        .eq("id", saving_id)
        .eq("school_id", school_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update saving")
    return _saving_row_to_out(updated.data[0])


async def delete_saving(school_id: str, saving_id: str) -> None:
    client = get_client()
    existing = (
        await client.table("expense_savings")
        .select("id")
        .eq("id", saving_id)
        .eq("school_id", school_id)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saving not found")
    await client.table("expense_savings").delete().eq("id", saving_id).eq("school_id", school_id).execute()


def _saving_row_to_out(row: dict) -> SavingOut:
    created_at = row.get("created_at")
    if isinstance(created_at, str):
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    elif isinstance(created_at, datetime):
        created_dt = created_at
    else:
        created_dt = datetime.now(timezone.utc)

    saved_date = row.get("saved_date")
    if hasattr(saved_date, "isoformat"):
        saved_date = saved_date.isoformat()
    elif saved_date is None:
        saved_date = date.today().isoformat()

    return SavingOut(
        id=row["id"],
        title=row["title"],
        amount=float(row.get("amount") or 0),
        saved_date=str(saved_date),
        sort_order=int(row.get("sort_order") or 0),
        created_at=created_dt,
    )


def _row_to_out(row: dict) -> ExpenseTransactionOut:
    created_at = row.get("created_at")
    if isinstance(created_at, str):
        created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    elif isinstance(created_at, datetime):
        created_dt = created_at
    else:
        created_dt = datetime.now(timezone.utc)

    tx_date = row.get("transaction_date")
    if hasattr(tx_date, "isoformat"):
        tx_date = tx_date.isoformat()
    elif tx_date is None:
        tx_date = date.today().isoformat()

    return ExpenseTransactionOut(
        id=row["id"],
        title=row["title"],
        amount=float(row.get("amount") or 0),
        type=row["type"],
        transaction_date=str(tx_date),
        created_at=created_dt,
        source="manual",
    )
