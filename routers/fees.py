"""Fees + payments (scoped per school)."""
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from database import get_client
from schemas.content import (
    FeeAmountIn,
    FeeItem,
    FeeStructureClassOut,
    FeeStructureSectionOut,
    FeeTransactionOut,
    StudentFeeDueIn,
    StudentFeeMarkPaidIn,
)
from schemas.student_fees import (
    FeeDiscountIn,
    FeeDiscountOut,
    FeeNoticeIn,
    FeeNoticeOut,
)
from services import fee_structure_service, student_fees_service, student_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/fees", tags=["fees"])

_COLUMNS = "id,school_id,student_email,title,amount,due_date,status,paid_at,created_at"

_FEE_ADMIN = require_roles(
    "school_admin", "office_staff", "principal", "vice_principal", "super_admin"
)


def _attendance_label(status: Optional[str]) -> str:
    raw = (status or "").strip().lower()
    if raw == "present":
        return "Present"
    if raw == "absent":
        return "Absent"
    if raw in ("leave", "holiday"):
        return raw.capitalize()
    return "Not marked"


def _is_current_month_fee(row: dict) -> bool:
    today = date.today()
    month_token = today.strftime("%b %Y")  # e.g. Jul 2026
    title = str(row.get("title") or "")
    if month_token.lower() in title.lower():
        return True
    due = str(row.get("due_date") or "")
    if len(due) >= 7:
        try:
            return due[:7] == f"{today.year:04d}-{today.month:02d}"
        except Exception:
            return False
    return False


async def _mark_fee_rows_paid(
    *,
    school_id: str,
    rows: list,
    now: str,
    custom_amount: Optional[float] = None,
    student_id: Optional[str] = None,
    student_email: Optional[str] = None,
) -> dict:
    """Mark pending fee rows paid. If custom_amount is set, apply FIFO partial payment.

    Also creates a ``fee_payments`` ledger row and generates a PDF receipt so the
    payment appears in Recent fees transactions with download/print.
    """
    import uuid

    client = get_client()
    marked = 0
    paid_total = 0.0
    remaining = None if custom_amount is None else float(custom_amount)
    method = "custom" if custom_amount is not None else "office"
    paid_fee_ids: list[str] = []

    for row in rows:
        fee_amount = float(row.get("amount") or 0)
        if fee_amount <= 0:
            continue
        if remaining is not None:
            if remaining <= 0:
                break
            pay_amount = min(fee_amount, remaining)
        else:
            pay_amount = fee_amount

        if remaining is not None and pay_amount < fee_amount:
            leftover = round(fee_amount - pay_amount, 2)
            await (
                client.table("fees")
                .update({"amount": leftover})
                .eq("id", row["id"])
                .eq("school_id", school_id)
                .execute()
            )
            await client.table("payments").insert(
                {
                    "school_id": school_id,
                    "fee_id": row["id"],
                    "amount": pay_amount,
                    "method": method,
                    "paid_at": now,
                }
            ).execute()
            paid_fee_ids.append(str(row["id"]))
            paid_total += pay_amount
            remaining -= pay_amount
            marked += 1
            continue

        await (
            client.table("fees")
            .update({"status": "paid", "paid_at": now})
            .eq("id", row["id"])
            .eq("school_id", school_id)
            .execute()
        )
        await client.table("payments").insert(
            {
                "school_id": school_id,
                "fee_id": row["id"],
                "amount": pay_amount,
                "method": method,
                "paid_at": now,
            }
        ).execute()
        paid_fee_ids.append(str(row["id"]))
        paid_total += pay_amount
        marked += 1
        if remaining is not None:
            remaining -= pay_amount

    receipt_id = None
    receipt_number = None
    pdf_url = None
    fee_payment_id = None

    if paid_total > 0:
        email = (student_email or "").strip().lower() or None
        if not email and rows:
            email = (rows[0].get("student_email") or "").strip().lower() or None
        invoice = f"INV-{uuid.uuid4().hex[:12].upper()}"
        payment_row = {
            "school_id": school_id,
            "student_id": student_id,
            "student_email": email,
            "fee_id": paid_fee_ids[0] if len(paid_fee_ids) == 1 else None,
            "invoice_number": invoice,
            "amount": round(paid_total, 2),
            "tax": 0,
            "discount": 0,
            "fine": 0,
            "total": round(paid_total, 2),
            "currency": "INR",
            "gateway_name": "office",
            "payment_status": "paid",
            "payment_method": method,
            "payment_date": now,
            "remarks": f"fees:{','.join(paid_fee_ids)}" if paid_fee_ids else None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            inserted = await client.table("fee_payments").insert(payment_row).execute()
            fp = (inserted.data or [None])[0]
            if fp:
                fee_payment_id = fp.get("id")
                from services.receipt.receipt_service import ensure_receipt_after_paid

                receipt_row = await ensure_receipt_after_paid(
                    {**payment_row, **fp, "payment_status": "paid"},
                    generated_by="office",
                )
                if receipt_row:
                    receipt_id = receipt_row.get("id")
                    receipt_number = receipt_row.get("receipt_number")
                    pdf_url = receipt_row.get("pdf_url")
        except Exception:
            # Payment still succeeded; receipt can be generated later.
            pass

    return {
        "ok": True,
        "marked": marked,
        "paid_total": round(paid_total, 2),
        "fee_payment_id": fee_payment_id,
        "receipt_id": receipt_id,
        "receipt_number": receipt_number,
        "pdf_url": pdf_url,
    }


@router.get("/me", response_model=List[FeeItem])
async def my_fees(user: dict = Depends(current_user)) -> List[FeeItem]:
    """Student fee list — all pending dues + paid rows within 18 months."""
    from services.fee_structure_service import FEE_RETENTION_MONTHS, months_ago_date

    client = get_client()
    school_id = user["school_id"]
    email = user["email"]
    cutoff = months_ago_date(FEE_RETENTION_MONTHS).isoformat()

    pending_res = (
        await client.table("fees")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("student_email", email)
        .eq("status", "pending")
        .order("due_date")
        .limit(200)
        .execute()
    )
    paid_res = (
        await client.table("fees")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("student_email", email)
        .eq("status", "paid")
        .gte("due_date", cutoff)
        .order("due_date", desc=True)
        .limit(200)
        .execute()
    )
    rows = list(pending_res.data or []) + list(paid_res.data or [])
    rows.sort(key=lambda r: str(r.get("due_date") or ""), reverse=True)
    return [FeeItem(**row) for row in rows]


@router.get("/school", response_model=List[FeeItem])
async def school_fees(user: dict = Depends(_FEE_ADMIN)) -> List[FeeItem]:
    """School-wide fee list for management dashboards.

    Returns recent paid fees first (for transactions), then pending rows (for due totals).
    """
    client = get_client()
    school_id = user["school_id"]
    paid_res = (
        await client.table("fees")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("status", "paid")
        .order("paid_at", desc=True)
        .limit(50)
        .execute()
    )
    pending_res = (
        await client.table("fees")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("status", "pending")
        .order("due_date", desc=True)
        .limit(500)
        .execute()
    )
    rows = list(paid_res.data or []) + list(pending_res.data or [])
    return [FeeItem(**row) for row in rows]


@router.get("/structure", response_model=List[FeeStructureClassOut])
async def fee_structure(user: dict = Depends(_FEE_ADMIN)) -> List[FeeStructureClassOut]:
    return await fee_structure_service.list_fee_structure(user["school_id"])


@router.get("/summary")
async def fee_summary(user: dict = Depends(_FEE_ADMIN)) -> dict:
    """Outstanding dues summary — same source as home Fees Due card."""
    return await fee_structure_service.school_fee_dashboard_stats(user["school_id"])


@router.get("/transactions", response_model=List[FeeTransactionOut])
async def fee_transactions(
    user: dict = Depends(_FEE_ADMIN),
    limit: int = 15,
    student_id: Optional[str] = Query(default=None),
) -> List[FeeTransactionOut]:
    """Recent fee payments (incl. custom/partial) + manually added dues.

    Paid entries prefer ``fee_payments`` (with receipt links) and also include
    office ``payments`` ledger rows that have no gateway payment row.
    """
    client = get_client()
    school_id = user["school_id"]
    capped = max(1, min(limit, 50))
    student_email_filter: Optional[str] = None
    if student_id:
        student = await student_service.get_student(school_id, student_id)
        student_email_filter = (student.email or "").strip().lower() or None

    fee_payments: list[dict] = []
    try:
        fp_query = (
            client.table("fee_payments")
            .select(
                "id,amount,total,student_email,student_id,fee_id,remarks,payment_method,"
                "gateway_name,payment_date,created_at,invoice_number,receipt_number,receipt_url"
            )
            .eq("school_id", school_id)
            .eq("payment_status", "paid")
        )
        if student_email_filter:
            fp_query = fp_query.eq("student_email", student_email_filter)
        fp_res = await fp_query.order("payment_date", desc=True).limit(capped).execute()
        fee_payments = fp_res.data or []
    except Exception:
        fee_payments = []

    fee_ids = [str(fp["fee_id"]) for fp in fee_payments if fp.get("fee_id")]
    if student_email_filter:
        filter_fee_res = (
            await client.table("fees")
            .select("id")
            .eq("school_id", school_id)
            .eq("student_email", student_email_filter)
            .limit(500)
            .execute()
        )
        fee_ids += [str(row["id"]) for row in (filter_fee_res.data or []) if row.get("id")]

    pay_query = (
        client.table("payments")
        .select("id,amount,method,paid_at,created_at,fee_id")
        .eq("school_id", school_id)
    )
    if fee_ids:
        pay_query = pay_query.in_("fee_id", list(set(fee_ids)))
    elif student_email_filter:
        payments = []
        pay_query = None
    if pay_query is not None:
        pay_res = await pay_query.order("paid_at", desc=True).limit(capped).execute()
        payments = pay_res.data or []
    else:
        payments = []

    receipt_by_payment: dict[str, dict] = {}
    try:
        receipt_res = (
            await client.table("fee_receipts")
            .select("id,receipt_number,pdf_url,payment_id,snapshot")
            .eq("school_id", school_id)
            .order("generated_at", desc=True)
            .limit(capped * 2)
            .execute()
        )
        for r in receipt_res.data or []:
            pid = str(r.get("payment_id") or "")
            if pid and pid not in receipt_by_payment:
                receipt_by_payment[pid] = r
    except Exception:
        receipt_by_payment = {}

    fee_ids = [str(p["fee_id"]) for p in payments if p.get("fee_id")]
    fee_ids += [str(fp["fee_id"]) for fp in fee_payments if fp.get("fee_id")]
    fee_by_id: dict[str, dict] = {}
    if fee_ids:
        fees_res = (
            await client.table("fees")
            .select("id,title,student_email,amount,status")
            .eq("school_id", school_id)
            .in_("id", list(set(fee_ids)))
            .execute()
        )
        for row in fees_res.data or []:
            fee_by_id[str(row["id"])] = row

    due_query = (
        client.table("fees")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .ilike("title", "Additional due%")
    )
    if student_email_filter:
        due_query = due_query.eq("student_email", student_email_filter)
    due_res = await due_query.order("created_at", desc=True).limit(capped).execute()

    emails = {
        (fee_by_id.get(str(p["fee_id"]), {}).get("student_email") or "").strip().lower()
        for p in payments
        if p.get("fee_id")
    }
    emails |= {
        (fp.get("student_email") or "").strip().lower()
        for fp in fee_payments
        if fp.get("student_email")
    }
    emails |= {
        (row.get("student_email") or "").strip().lower()
        for row in (due_res.data or [])
        if row.get("student_email")
    }
    emails.discard("")

    name_by_email: dict[str, str] = {}
    student_meta_by_email: dict[str, dict] = {}
    if emails:
        users_res = (
            await client.table("users")
            .select("id,email,full_name")
            .eq("school_id", school_id)
            .in_("email", list(emails))
            .execute()
        )
        user_id_by_email: dict[str, str] = {}
        for u in users_res.data or []:
            email = (u.get("email") or "").strip().lower()
            if email:
                name_by_email[email] = (u.get("full_name") or "").strip()
                if u.get("id"):
                    user_id_by_email[email] = str(u["id"])

        user_ids = list(user_id_by_email.values())
        if user_ids:
            try:
                stu_res = (
                    await client.table("students")
                    .select("user_id,admission_no,roll_no,class_id,section_id")
                    .eq("school_id", school_id)
                    .in_("user_id", user_ids)
                    .execute()
                )
                class_ids = {
                    str(s["class_id"]) for s in (stu_res.data or []) if s.get("class_id")
                }
                section_ids = {
                    str(s["section_id"]) for s in (stu_res.data or []) if s.get("section_id")
                }
                class_name_by_id: dict[str, str] = {}
                section_name_by_id: dict[str, str] = {}
                if class_ids:
                    cls_res = (
                        await client.table("classes")
                        .select("id,name")
                        .eq("school_id", school_id)
                        .in_("id", list(class_ids))
                        .execute()
                    )
                    for c in cls_res.data or []:
                        class_name_by_id[str(c["id"])] = c.get("name") or ""
                if section_ids:
                    sec_res = (
                        await client.table("sections")
                        .select("id,name")
                        .eq("school_id", school_id)
                        .in_("id", list(section_ids))
                        .execute()
                    )
                    for s in sec_res.data or []:
                        section_name_by_id[str(s["id"])] = s.get("name") or ""

                email_by_user_id = {uid: email for email, uid in user_id_by_email.items()}
                for s in stu_res.data or []:
                    email = email_by_user_id.get(str(s.get("user_id") or ""))
                    if not email:
                        continue
                    student_meta_by_email[email] = {
                        "admission_no": s.get("admission_no"),
                        "roll_no": s.get("roll_no"),
                        "class_name": class_name_by_id.get(str(s.get("class_id") or "")) or None,
                        "section_name": section_name_by_id.get(str(s.get("section_id") or ""))
                        or None,
                    }
            except Exception:
                student_meta_by_email = {}

    def _student_fields(email: str) -> dict:
        meta = student_meta_by_email.get(email) or {}
        return {
            "student_name": name_by_email.get(email) or None,
            "admission_no": meta.get("admission_no"),
            "roll_no": meta.get("roll_no"),
            "class_name": meta.get("class_name"),
            "section_name": meta.get("section_name"),
        }

    rows: list[FeeTransactionOut] = []

    for fp in fee_payments:
        email = (fp.get("student_email") or "").strip().lower()
        method = (fp.get("payment_method") or fp.get("gateway_name") or "").strip().lower()
        if method == "custom":
            title = "Custom pay"
            status_label = "Custom pay"
        else:
            title = "Fees paid"
            status_label = "Fees paid"
        receipt = receipt_by_payment.get(str(fp["id"]))
        snap_student = ((receipt or {}).get("snapshot") or {}).get("student") or {}
        occurred = fp.get("payment_date") or fp.get("created_at")
        rows.append(
            FeeTransactionOut(
                id=f"fpay-{fp['id']}",
                title=title,
                amount=float(fp.get("total") or fp.get("amount") or 0),
                student_email=email or None,
                kind="paid",
                status_label=status_label,
                occurred_at=str(occurred) if occurred else None,
                receipt_id=(receipt or {}).get("id"),
                receipt_number=(receipt or {}).get("receipt_number") or fp.get("receipt_number"),
                pdf_url=(receipt or {}).get("pdf_url") or fp.get("receipt_url"),
                payment_method=fp.get("payment_method") or method or None,
                invoice_number=fp.get("invoice_number"),
                gateway_name=fp.get("gateway_name"),
                student_name=name_by_email.get(email)
                or snap_student.get("full_name")
                or None,
                admission_no=snap_student.get("admission_no")
                or _student_fields(email).get("admission_no"),
                roll_no=snap_student.get("roll_no") or _student_fields(email).get("roll_no"),
                class_name=snap_student.get("class_name")
                or _student_fields(email).get("class_name"),
                section_name=snap_student.get("section_name")
                or _student_fields(email).get("section_name"),
            )
        )

    # Office / ledger payments without a matching fee_payments row
    fp_fee_ids = set()
    for fp in fee_payments:
        if fp.get("fee_id"):
            fp_fee_ids.add(str(fp["fee_id"]))
        remarks = fp.get("remarks") or ""
        if remarks.startswith("fees:"):
            fp_fee_ids.update(x for x in remarks[5:].split(",") if x)

    for p in payments:
        fee_id = str(p.get("fee_id") or "")
        if fee_id and fee_id in fp_fee_ids:
            continue
        fee = fee_by_id.get(fee_id, {}) if fee_id else {}
        email = (fee.get("student_email") or "").strip().lower()
        occurred = p.get("paid_at") or p.get("created_at")
        method = (p.get("method") or "").strip().lower()
        if method == "custom":
            title = "Custom pay"
            status_label = "Custom pay"
        else:
            title = "Fees paid"
            status_label = "Fees paid"
        fields = _student_fields(email)
        rows.append(
            FeeTransactionOut(
                id=f"pay-{p['id']}",
                title=title,
                amount=float(p.get("amount") or 0),
                student_email=email or None,
                kind="paid",
                status_label=status_label,
                occurred_at=str(occurred) if occurred else None,
                payment_method=method or None,
                **{k: fields[k] for k in ("student_name", "admission_no", "roll_no", "class_name", "section_name")},
            )
        )

    for row in due_res.data or []:
        email = (row.get("student_email") or "").strip().lower()
        occurred = row.get("created_at") or row.get("due_date")
        raw_title = (row.get("title") or "Additional due").strip()
        reason = raw_title
        if reason.lower().startswith("additional due —"):
            reason = reason.split("—", 1)[1].strip() or "Additional due"
        elif reason.lower().startswith("additional due -"):
            reason = reason.split("-", 1)[1].strip() or "Additional due"
        fields = _student_fields(email)
        rows.append(
            FeeTransactionOut(
                id=f"due-{row['id']}",
                title="Add due",
                amount=float(row.get("amount") or 0),
                student_email=email or None,
                kind="due_added",
                status_label="Add due",
                occurred_at=str(occurred) if occurred else None,
                due_reason=reason if reason.lower() != "additional due" else None,
                **{k: fields[k] for k in ("student_name", "admission_no", "roll_no", "class_name", "section_name")},
            )
        )

    rows.sort(key=lambda item: item.occurred_at or "", reverse=True)
    return rows[:capped]


@router.put("/structure/class/{class_id}", response_model=FeeStructureClassOut)
async def set_class_fee(
    class_id: str,
    body: FeeAmountIn,
    user: dict = Depends(_FEE_ADMIN),
) -> FeeStructureClassOut:
    return await fee_structure_service.set_class_monthly_amount(
        user["school_id"], class_id, body.amount
    )


@router.put("/structure/section/{section_id}", response_model=FeeStructureSectionOut)
async def set_section_fee(
    section_id: str,
    body: FeeAmountIn,
    user: dict = Depends(_FEE_ADMIN),
) -> FeeStructureSectionOut:
    return await fee_structure_service.set_section_monthly_amount(
        user["school_id"], section_id, body.amount
    )


@router.get("/student/{student_id}/details")
async def student_fee_details(
    student_id: str,
    user: dict = Depends(
        require_roles(
            "school_admin",
            "office_staff",
            "principal",
            "vice_principal",
            "super_admin",
            "teacher",
        )
    ),
) -> dict:
    school_id = user["school_id"]
    student = await student_service.get_student(school_id, student_id)
    email = (student.email or "").strip().lower()
    client = get_client()
    today = date.today().isoformat()

    attendance_status = None
    if email:
        att = (
            await client.table("attendance")
            .select("status")
            .eq("school_id", school_id)
            .eq("student_email", email)
            .eq("date", today)
            .limit(1)
            .execute()
        )
        if att.data:
            attendance_status = att.data[0].get("status")

    pending: list = []
    total_due = 0.0
    this_month_due = 0.0
    is_teacher = user.get("role") == "teacher"
    if email and not is_teacher:
        fees_res = (
            await client.table("fees")
            .select(_COLUMNS)
            .eq("school_id", school_id)
            .eq("student_email", email)
            .eq("status", "pending")
            .order("due_date")
            .limit(100)
            .execute()
        )
        pending = fees_res.data or []
        total_due = round(sum(float(row.get("amount") or 0) for row in pending), 2)
        this_month_due = round(
            sum(float(row.get("amount") or 0) for row in pending if _is_current_month_fee(row)),
            2,
        )

    payload = {
        "student": {
            "id": student.id,
            "full_name": student.full_name,
            "admission_no": student.admission_no,
            "class_name": student.class_name,
            "section_name": student.section_name,
            "roll_no": student.roll_no,
            "email": student.email,
        },
        "attendance_today": _attendance_label(attendance_status),
        "attendance_status": attendance_status or "not_marked",
    }
    if is_teacher:
        return payload
    payload.update(
        {
            "fees_due": total_due,
            "this_month_due": this_month_due,
            "pending_fees": [FeeItem(**row).model_dump() for row in pending],
        }
    )
    return payload


@router.post("/student/{student_id}/due")
async def add_student_due(
    student_id: str,
    body: StudentFeeDueIn,
    user: dict = Depends(_FEE_ADMIN),
) -> dict:
    school_id = user["school_id"]
    student = await student_service.get_student(school_id, student_id)
    email = (student.email or "").strip().lower()
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student has no email linked for fees")

    due_date = (body.due_date or date.today().isoformat())[:10]
    raw_title = (body.title or "").strip()
    if not raw_title or raw_title.lower() in ("additional due", "add due"):
        title = "Additional due"
    elif raw_title.lower().startswith("additional due"):
        title = raw_title
    else:
        # Keep "Additional due — …" prefix so dues stay identifiable in feeds,
        # while the reason is visible to parents on the fee itself.
        title = f"Additional due — {raw_title}"
    client = get_client()
    inserted = (
        await client.table("fees")
        .insert(
            {
                "school_id": school_id,
                "student_email": email,
                "title": title,
                "amount": float(body.amount),
                "due_date": due_date,
                "status": "pending",
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to add due")
    return {"ok": True, "fee": FeeItem(**inserted.data[0]).model_dump()}


@router.post("/student/{student_id}/mark-paid")
async def mark_student_fees_paid(
    student_id: str,
    body: StudentFeeMarkPaidIn,
    user: dict = Depends(_FEE_ADMIN),
) -> dict:
    school_id = user["school_id"]
    student = await student_service.get_student(school_id, student_id)
    email = (student.email or "").strip().lower()
    if not email:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student has no email linked for fees")

    client = get_client()
    now = datetime.now(timezone.utc).isoformat()
    pending = (
        await client.table("fees")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("student_email", email)
        .eq("status", "pending")
        .order("due_date")
        .limit(200)
        .execute()
    )
    rows = pending.data or []
    if not rows:
        return {"ok": True, "marked": 0, "paid_total": 0, "mode": body.mode}

    mode = body.mode
    if mode == "this_month":
        rows = [row for row in rows if _is_current_month_fee(row)]
        if not rows:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "No pending fees for this month",
            )
        result = await _mark_fee_rows_paid(
            school_id=school_id,
            rows=rows,
            now=now,
            student_id=student.id,
            student_email=email,
        )
    elif mode == "custom":
        if body.amount is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Custom amount is required")
        result = await _mark_fee_rows_paid(
            school_id=school_id,
            rows=rows,
            now=now,
            custom_amount=float(body.amount),
            student_id=student.id,
            student_email=email,
        )
    else:
        result = await _mark_fee_rows_paid(
            school_id=school_id,
            rows=rows,
            now=now,
            student_id=student.id,
            student_email=email,
        )

    result["mode"] = mode
    return result


@router.post("/{fee_id}/pay")
async def pay_fee(fee_id: str, user: dict = Depends(current_user)) -> dict:
    """Legacy in-app mark-paid.

    Disabled when the school has an active payment gateway — students must use
    POST /student/fees/create-order and verified webhook/signature flow instead.
    """
    from services.payment import gateway_service

    active = await gateway_service.get_active_gateway_row(user["school_id"])
    if active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Online payment gateway is enabled. Use /api/student/fees/create-order "
            "and complete payment through the gateway. The app cannot mark fees paid.",
        )

    client = get_client()
    now = datetime.now(timezone.utc).isoformat()

    existing = (
        await client.table("fees")
        .select("id,amount")
        .eq("id", fee_id)
        .eq("school_id", user["school_id"])
        .eq("student_email", user["email"])
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee not found")

    updated = (
        await client.table("fees")
        .update({"status": "paid", "paid_at": now})
        .eq("id", fee_id)
        .eq("school_id", user["school_id"])
        .eq("student_email", user["email"])
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Fee not found")

    fee = existing.data[0]
    await (
        client.table("payments")
        .insert(
            {
                "school_id": user["school_id"],
                "fee_id": fee_id,
                "amount": fee.get("amount", 0),
                "method": "in_app",
                "paid_at": now,
            }
        )
        .execute()
    )
    return {"ok": True}


# ---------------------------------------------------------------------------
# Fee discounts / scholarships / concessions (admin CRUD)
# ---------------------------------------------------------------------------


@router.get("/discounts", response_model=List[FeeDiscountOut])
async def list_fee_discounts(
    student_id: Optional[str] = Query(default=None),
    user: dict = Depends(_FEE_ADMIN),
) -> List[FeeDiscountOut]:
    return await student_fees_service.list_fee_discounts(user["school_id"], student_id)


@router.post("/discounts", response_model=FeeDiscountOut)
async def create_fee_discount(
    body: FeeDiscountIn,
    user: dict = Depends(_FEE_ADMIN),
) -> FeeDiscountOut:
    return await student_fees_service.create_fee_discount(user["school_id"], user["id"], body)


@router.delete("/discounts/{discount_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_discount(
    discount_id: str,
    user: dict = Depends(_FEE_ADMIN),
) -> Response:
    await student_fees_service.delete_fee_discount(user["school_id"], discount_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Fee notices (admin CRUD)
# ---------------------------------------------------------------------------


@router.get("/notices", response_model=List[FeeNoticeOut])
async def list_fee_notices(user: dict = Depends(_FEE_ADMIN)) -> List[FeeNoticeOut]:
    return await student_fees_service.list_fee_notices(user["school_id"])


@router.post("/notices", response_model=FeeNoticeOut)
async def create_fee_notice(
    body: FeeNoticeIn,
    user: dict = Depends(_FEE_ADMIN),
) -> FeeNoticeOut:
    return await student_fees_service.create_fee_notice(user["school_id"], user["id"], body)


@router.delete("/notices/{notice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fee_notice(
    notice_id: str,
    user: dict = Depends(_FEE_ADMIN),
) -> Response:
    await student_fees_service.delete_fee_notice(user["school_id"], notice_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
