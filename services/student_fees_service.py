"""Comprehensive student fees overview service.

Builds the payload for the student/parent fees page: overview totals,
fee components with computed statuses, payment history with receipts,
discounts/scholarships, and fee notices.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.student_fees import (
    FeeComponentOut,
    FeeDiscountIn,
    FeeDiscountOut,
    FeeNoticeIn,
    FeeNoticeOut,
    FeeOverviewOut,
    FeePaymentHistoryOut,
)
from services.fee_structure_service import FEE_RETENTION_MONTHS, months_ago_date


def _today() -> date:
    return date.today()


def _academic_session_label(today: Optional[date] = None) -> str:
    """Academic session typically runs Apr–Mar; fall back to calendar year."""
    today = today or _today()
    if today.month >= 4:
        return f"{today.year}-{today.year + 1}"
    return f"{today.year - 1}-{today.year}"


def _compute_status(
    *,
    fee_status: str,
    amount: float,
    original_amount: float,
    due_date: Optional[str],
    today: date,
) -> str:
    """Compute display status: paid | partially_paid | pending | overdue."""
    if fee_status == "paid":
        return "paid"
    # Pending but partially paid
    if original_amount and amount < original_amount and amount > 0:
        return "partially_paid"
    if amount <= 0:
        return "paid"
    # Check overdue
    if due_date:
        try:
            due = date.fromisoformat(str(due_date)[:10])
            if due < today:
                return "overdue"
        except (ValueError, TypeError):
            pass
    return "pending"


async def _get_student_id(school_id: str, user_id: str) -> Optional[str]:
    client = get_client()
    res = (
        await client.table("students")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if res.data:
        return str(res.data[0]["id"])
    return None


async def _get_student_class_info(
    school_id: str, student_id: str
) -> tuple[Optional[str], Optional[str]]:
    """Return (class_id, section_id) for the student."""
    client = get_client()
    res = (
        await client.table("students")
        .select("class_id,section_id")
        .eq("school_id", school_id)
        .eq("id", student_id)
        .limit(1)
        .execute()
    )
    if res.data:
        row = res.data[0]
        return row.get("class_id"), row.get("section_id")
    return None, None


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


async def get_student_fees_overview(user: dict) -> FeeOverviewOut:
    """Build the comprehensive fees overview for a student/parent."""
    if user.get("role") not in ("student", "parent"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students and parents can view this")

    school_id = user["school_id"]
    email = (user.get("email") or "").strip().lower()
    today = _today()
    session_label = _academic_session_label(today)

    client = get_client()

    # Ensure current month fees are generated
    try:
        from services.fee_structure_service import ensure_current_month_fees

        await ensure_current_month_fees(school_id)
    except Exception:
        pass

    student_id = await _get_student_id(school_id, user["id"])

    # --- Fetch fee rows (pending + recent paid) ---
    cutoff = months_ago_date(FEE_RETENTION_MONTHS).isoformat()
    fee_columns = "id,title,amount,original_amount,due_date,status,paid_at,created_at"

    pending_res = (
        await client.table("fees")
        .select(fee_columns)
        .eq("school_id", school_id)
        .eq("student_email", email)
        .eq("status", "pending")
        .order("due_date")
        .limit(300)
        .execute()
    )
    paid_res = (
        await client.table("fees")
        .select(fee_columns)
        .eq("school_id", school_id)
        .eq("student_email", email)
        .eq("status", "paid")
        .gte("due_date", cutoff)
        .order("due_date", desc=True)
        .limit(300)
        .execute()
    )

    all_fee_rows = list(pending_res.data or []) + list(paid_res.data or [])

    # --- Build fee components ---
    components: List[FeeComponentOut] = []
    for row in all_fee_rows:
        amt = float(row.get("amount") or 0)
        orig = float(row.get("original_amount") or amt or amt)
        if orig <= 0:
            orig = amt
        fee_status = str(row.get("status") or "pending")
        amount_paid = round(orig - amt, 2) if fee_status == "pending" and orig > amt else (orig if fee_status == "paid" else 0.0)
        if fee_status == "paid":
            amount_paid = orig
            amt = 0.0
        display_status = _compute_status(
            fee_status=fee_status,
            amount=amt,
            original_amount=orig,
            due_date=row.get("due_date"),
            today=today,
        )
        components.append(
            FeeComponentOut(
                id=str(row.get("id") or ""),
                title=str(row.get("title") or ""),
                amount=round(amt, 2),
                original_amount=round(orig, 2),
                amount_paid=round(amount_paid, 2),
                due_date=str(row.get("due_date") or "") or None,
                status=display_status,  # type: ignore[arg-type]
                paid_at=str(row.get("paid_at") or "") or None,
                created_at=str(row.get("created_at") or "") or None,
            )
        )

    # Sort: overdue first, then pending, partially_paid, paid
    status_order = {"overdue": 0, "pending": 1, "partially_paid": 2, "paid": 3}
    components.sort(key=lambda c: (status_order.get(c.status, 9), c.due_date or ""))

    # --- Compute overview totals ---
    total_fees = round(sum(c.original_amount for c in components), 2)
    total_paid = round(sum(c.amount_paid for c in components), 2)
    remaining_balance = round(sum(c.amount for c in components if c.status != "paid"), 2)
    overdue_amount = round(sum(c.amount for c in components if c.status == "overdue"), 2)
    upcoming_amount = round(
        sum(c.amount for c in components if c.status == "pending"), 2
    )

    # Next payment due date = earliest non-paid, non-overdue due date
    upcoming_dates = sorted(
        [
            c.due_date
            for c in components
            if c.due_date and c.status in ("pending", "partially_paid")
        ]
    )
    next_payment_due_date = upcoming_dates[0] if upcoming_dates else None

    # If no upcoming, use earliest overdue
    if not next_payment_due_date:
        overdue_dates = sorted(
            [c.due_date for c in components if c.due_date and c.status == "overdue"]
        )
        if overdue_dates:
            next_payment_due_date = overdue_dates[0]

    # --- Upcoming & overdue lists ---
    upcoming = [c for c in components if c.status in ("pending", "partially_paid")]
    overdue = [c for c in components if c.status == "overdue"]

    # --- Payment history (from fee_payments + receipts) ---
    payments: List[FeePaymentHistoryOut] = []
    try:
        pay_q = (
            client.table("fee_payments")
            .select(
                "id,invoice_number,amount,total,currency,gateway_name,payment_method,"
                "payment_status,payment_date,receipt_number,receipt_url,"
                "transaction_reference,fee_id"
            )
            .eq("school_id", school_id)
            .eq("payment_status", "paid")
        )
        if student_id:
            pay_q = pay_q.eq("student_id", student_id)
        else:
            pay_q = pay_q.eq("student_email", email)
        pay_res = await pay_q.order("payment_date", desc=True).limit(50).execute()

        # Fetch receipt info
        payment_ids = [str(r["id"]) for r in (pay_res.data or []) if r.get("id")]
        receipt_by_payment: dict[str, dict] = {}
        if payment_ids:
            try:
                receipt_res = (
                    await client.table("fee_receipts")
                    .select("id,payment_id,pdf_url,receipt_number")
                    .eq("school_id", school_id)
                    .in_("payment_id", payment_ids)
                    .execute()
                )
                for r in receipt_res.data or []:
                    pid = str(r.get("payment_id") or "")
                    if pid:
                        receipt_by_payment[pid] = r
            except Exception:
                pass

        # Fetch fee titles
        fee_ids = [str(r["fee_id"]) for r in (pay_res.data or []) if r.get("fee_id")]
        fee_title_by_id: dict[str, str] = {}
        if fee_ids:
            try:
                fees_res = (
                    await client.table("fees")
                    .select("id,title")
                    .eq("school_id", school_id)
                    .in_("id", list(set(fee_ids)))
                    .execute()
                )
                for f in fees_res.data or []:
                    fee_title_by_id[str(f["id"])] = f.get("title") or ""
            except Exception:
                pass

        for row in pay_res.data or []:
            pid = str(row.get("id") or "")
            receipt = receipt_by_payment.get(pid, {})
            payments.append(
                FeePaymentHistoryOut(
                    id=pid,
                    invoice_number=row.get("invoice_number"),
                    amount=float(row.get("amount") or 0),
                    total=float(row.get("total") or row.get("amount") or 0),
                    currency=row.get("currency") or "INR",
                    gateway_name=row.get("gateway_name"),
                    payment_method=row.get("payment_method"),
                    payment_status=row.get("payment_status") or "paid",
                    payment_date=str(row.get("payment_date") or "") or None,
                    receipt_number=receipt.get("receipt_number") or row.get("receipt_number"),
                    receipt_url=receipt.get("pdf_url") or row.get("receipt_url"),
                    receipt_id=receipt.get("id"),
                    transaction_reference=row.get("transaction_reference"),
                    fee_title=fee_title_by_id.get(str(row.get("fee_id") or "")),
                )
            )
    except Exception:
        payments = []

    # --- Discounts / scholarships / concessions ---
    discounts: List[FeeDiscountOut] = []
    try:
        disc_q = (
            client.table("fee_discounts")
            .select("*")
            .eq("school_id", school_id)
            .eq("is_active", True)
        )
        if student_id:
            disc_q = disc_q.or_(f"student_id.eq.{student_id},student_email.eq.{email}")
        else:
            disc_q = disc_q.eq("student_email", email)
        disc_res = await disc_q.order("created_at", desc=True).limit(50).execute()
        for row in disc_res.data or []:
            discounts.append(
                FeeDiscountOut(
                    id=str(row.get("id") or ""),
                    discount_type=row.get("discount_type") or "concession",  # type: ignore[arg-type]
                    name=row.get("name") or "",
                    description=row.get("description") or None,
                    original_amount=float(row.get("original_amount") or 0),
                    discount_amount=float(row.get("discount_amount") or 0),
                    final_amount=float(row.get("final_amount") or 0),
                    reason=row.get("reason") or None,
                    is_active=row.get("is_active", True),
                    valid_from=str(row.get("valid_from") or "") or None,
                    valid_to=str(row.get("valid_to") or "") or None,
                    created_at=str(row.get("created_at") or "") or None,
                )
            )
    except Exception:
        discounts = []

    # --- Fee notices ---
    notices: List[FeeNoticeOut] = []
    try:
        class_id: Optional[str] = None
        section_id: Optional[str] = None
        if student_id:
            class_id, section_id = await _get_student_class_info(school_id, student_id)

        notice_q = (
            client.table("fee_notices")
            .select("id,title,body,notice_type,priority,is_pinned,published_at,expires_at,target_class_id,target_section_id")
            .eq("school_id", school_id)
            .eq("is_active", True)
            .order("is_pinned", desc=True)
            .order("published_at", desc=True)
            .limit(20)
            .execute()
        )
        for row in notice_q.data or []:
            # Filter notices targeted to specific class/section
            target_class = row.get("target_class_id")
            target_section = row.get("target_section_id")
            if target_class and class_id and str(target_class) != str(class_id):
                continue
            if target_section and section_id and str(target_section) != str(section_id):
                continue
            # Skip expired
            expires = row.get("expires_at")
            if expires:
                try:
                    exp_dt = datetime.fromisoformat(str(expires).replace("Z", "+00:00"))
                    if exp_dt < datetime.now(timezone.utc):
                        continue
                except (ValueError, TypeError):
                    pass
            notices.append(
                FeeNoticeOut(
                    id=str(row.get("id") or ""),
                    title=row.get("title") or "",
                    body=row.get("body") or None,
                    notice_type=row.get("notice_type") or "reminder",  # type: ignore[arg-type]
                    priority=row.get("priority") or "normal",  # type: ignore[arg-type]
                    is_pinned=row.get("is_pinned", False),
                    published_at=str(row.get("published_at") or "") or "",
                    expires_at=str(row.get("expires_at") or "") or None,
                )
            )
    except Exception:
        notices = []

    # --- Check if online payment gateway is enabled ---
    online_payment_enabled = False
    try:
        from services.payment import gateway_service

        active = await gateway_service.get_active_gateway_row(school_id)
        online_payment_enabled = active is not None
    except Exception:
        online_payment_enabled = False

    return FeeOverviewOut(
        total_fees=total_fees,
        total_paid=total_paid,
        remaining_balance=remaining_balance,
        overdue_amount=overdue_amount,
        upcoming_amount=upcoming_amount,
        next_payment_due_date=next_payment_due_date,
        academic_session=session_label,
        components=components,
        payments=payments,
        upcoming=upcoming,
        overdue=overdue,
        discounts=discounts,
        notices=notices,
        online_payment_enabled=online_payment_enabled,
    )


# ---------------------------------------------------------------------------
# Admin: Discounts CRUD
# ---------------------------------------------------------------------------


async def create_fee_discount(school_id: str, created_by: str, body: FeeDiscountIn) -> FeeDiscountOut:
    client = get_client()
    row = {
        "school_id": school_id,
        "student_id": body.student_id,
        "student_email": (body.student_email or "").strip().lower() or None,
        "discount_type": body.discount_type,
        "name": body.name,
        "description": body.description or None,
        "original_amount": float(body.original_amount),
        "discount_amount": float(body.discount_amount),
        "final_amount": float(body.final_amount),
        "reason": body.reason or None,
        "authorized_by": created_by,
        "valid_from": body.valid_from or None,
        "valid_to": body.valid_to or None,
    }
    res = await client.table("fee_discounts").insert(row).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create discount")
    r = res.data[0]
    return FeeDiscountOut(
        id=str(r.get("id") or ""),
        discount_type=r.get("discount_type") or "concession",  # type: ignore[arg-type]
        name=r.get("name") or "",
        description=r.get("description") or None,
        original_amount=float(r.get("original_amount") or 0),
        discount_amount=float(r.get("discount_amount") or 0),
        final_amount=float(r.get("final_amount") or 0),
        reason=r.get("reason") or None,
        is_active=r.get("is_active", True),
        valid_from=str(r.get("valid_from") or "") or None,
        valid_to=str(r.get("valid_to") or "") or None,
        created_at=str(r.get("created_at") or "") or None,
    )


async def list_fee_discounts(school_id: str, student_id: Optional[str] = None) -> List[FeeDiscountOut]:
    client = get_client()
    q = client.table("fee_discounts").select("*").eq("school_id", school_id)
    if student_id:
        q = q.eq("student_id", student_id)
    res = await q.order("created_at", desc=True).limit(100).execute()
    out: List[FeeDiscountOut] = []
    for r in res.data or []:
        out.append(
            FeeDiscountOut(
                id=str(r.get("id") or ""),
                discount_type=r.get("discount_type") or "concession",  # type: ignore[arg-type]
                name=r.get("name") or "",
                description=r.get("description") or None,
                original_amount=float(r.get("original_amount") or 0),
                discount_amount=float(r.get("discount_amount") or 0),
                final_amount=float(r.get("final_amount") or 0),
                reason=r.get("reason") or None,
                is_active=r.get("is_active", True),
                valid_from=str(r.get("valid_from") or "") or None,
                valid_to=str(r.get("valid_to") or "") or None,
                created_at=str(r.get("created_at") or "") or None,
            )
        )
    return out


async def delete_fee_discount(school_id: str, discount_id: str) -> None:
    client = get_client()
    await (
        client.table("fee_discounts")
        .delete()
        .eq("id", discount_id)
        .eq("school_id", school_id)
        .execute()
    )


# ---------------------------------------------------------------------------
# Admin: Notices CRUD
# ---------------------------------------------------------------------------


async def create_fee_notice(school_id: str, created_by: str, body: FeeNoticeIn) -> FeeNoticeOut:
    client = get_client()
    row = {
        "school_id": school_id,
        "title": body.title,
        "body": body.body or None,
        "notice_type": body.notice_type,
        "priority": body.priority,
        "target_class_id": body.target_class_id or None,
        "target_section_id": body.target_section_id or None,
        "is_pinned": body.is_pinned,
        "created_by": created_by,
        "expires_at": body.expires_at or None,
    }
    res = await client.table("fee_notices").insert(row).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create notice")
    r = res.data[0]
    return FeeNoticeOut(
        id=str(r.get("id") or ""),
        title=r.get("title") or "",
        body=r.get("body") or None,
        notice_type=r.get("notice_type") or "reminder",  # type: ignore[arg-type]
        priority=r.get("priority") or "normal",  # type: ignore[arg-type]
        is_pinned=r.get("is_pinned", False),
        published_at=str(r.get("published_at") or "") or "",
        expires_at=str(r.get("expires_at") or "") or None,
    )


async def list_fee_notices(school_id: str) -> List[FeeNoticeOut]:
    client = get_client()
    res = (
        await client.table("fee_notices")
        .select("*")
        .eq("school_id", school_id)
        .order("is_pinned", desc=True)
        .order("published_at", desc=True)
        .limit(100)
        .execute()
    )
    out: List[FeeNoticeOut] = []
    for r in res.data or []:
        out.append(
            FeeNoticeOut(
                id=str(r.get("id") or ""),
                title=r.get("title") or "",
                body=r.get("body") or None,
                notice_type=r.get("notice_type") or "reminder",  # type: ignore[arg-type]
                priority=r.get("priority") or "normal",  # type: ignore[arg-type]
                is_pinned=r.get("is_pinned", False),
                published_at=str(r.get("published_at") or "") or "",
                expires_at=str(r.get("expires_at") or "") or None,
            )
        )
    return out


async def delete_fee_notice(school_id: str, notice_id: str) -> None:
    client = get_client()
    await (
        client.table("fee_notices")
        .delete()
        .eq("id", notice_id)
        .eq("school_id", school_id)
        .execute()
    )
