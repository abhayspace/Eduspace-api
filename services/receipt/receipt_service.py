"""Fee receipt orchestration: snapshot → number → PDF → persist → link payment."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

from database import get_client
from services.receipt.receipt_generator import generate_receipt_pdf
from services.receipt.receipt_number import next_receipt_number
from services.receipt.storage import ReceiptStorage, default_storage

logger = logging.getLogger("eduspace.receipt")

_TERMINAL_NON_PAID = {"pending", "created", "failed", "cancelled", "refunded"}


def _fee_ids_from_payment(payment: dict[str, Any]) -> list[str]:
    remarks = payment.get("remarks") or ""
    if remarks.startswith("fees:"):
        return [x for x in remarks[5:].split(",") if x]
    if payment.get("fee_id"):
        return [str(payment["fee_id"])]
    return []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _year_from_iso(value: Optional[str]) -> int:
    if value:
        try:
            return int(str(value)[:4])
        except ValueError:
            pass
    return datetime.now(timezone.utc).year


async def _load_school(school_id: str) -> dict[str, Any]:
    client = get_client()
    res = (
        await client.table("schools")
        .select(
            "id,school_name,institution_code,logo_url,address,city,state,pincode,"
            "phone,email,website,gst_number"
        )
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return res.data[0]


async def _load_student(
    school_id: str,
    *,
    student_id: Optional[str],
    student_email: Optional[str],
) -> dict[str, Any]:
    client = get_client()
    profile: dict[str, Any] = {}

    if student_id:
        res = (
            await client.table("students")
            .select("id,user_id,admission_no,roll_no,class_id,section_id")
            .eq("school_id", school_id)
            .eq("id", student_id)
            .limit(1)
            .execute()
        )
        profile = (res.data or [{}])[0] if res.data else {}
    elif student_email:
        email = student_email.strip().lower()
        user_res = (
            await client.table("users")
            .select("id,email,full_name")
            .eq("school_id", school_id)
            .eq("email", email)
            .limit(1)
            .execute()
        )
        user = (user_res.data or [{}])[0] if user_res.data else {}
        if user.get("id"):
            stu_res = (
                await client.table("students")
                .select("id,user_id,admission_no,roll_no,class_id,section_id")
                .eq("school_id", school_id)
                .eq("user_id", user["id"])
                .limit(1)
                .execute()
            )
            profile = (stu_res.data or [{}])[0] if stu_res.data else {}
            profile = {
                **profile,
                "email": user.get("email") or email,
                "full_name": user.get("full_name"),
            }
        else:
            return {"email": email}
    else:
        return {}

    if not profile:
        return {}

    if not profile.get("full_name") and profile.get("user_id"):
        user_res = (
            await client.table("users")
            .select("id,email,full_name")
            .eq("id", profile["user_id"])
            .limit(1)
            .execute()
        )
        if user_res.data:
            profile["email"] = user_res.data[0].get("email") or profile.get("email")
            profile["full_name"] = user_res.data[0].get("full_name")

    class_name = None
    section_name = None
    if profile.get("class_id"):
        cls = (
            await client.table("classes")
            .select("name")
            .eq("id", profile["class_id"])
            .limit(1)
            .execute()
        )
        class_name = (cls.data or [{}])[0].get("name")
    if profile.get("section_id"):
        sec = (
            await client.table("sections")
            .select("name")
            .eq("id", profile["section_id"])
            .limit(1)
            .execute()
        )
        section_name = (sec.data or [{}])[0].get("name")

    return {
        "id": profile.get("id"),
        "full_name": profile.get("full_name"),
        "admission_no": profile.get("admission_no"),
        "roll_no": profile.get("roll_no"),
        "email": profile.get("email") or student_email,
        "class_name": class_name,
        "section_name": section_name,
        "class_id": profile.get("class_id"),
        "section_id": profile.get("section_id"),
    }


async def _load_fee_lines(school_id: str, payment: dict[str, Any]) -> list[dict[str, Any]]:
    fee_ids = _fee_ids_from_payment(payment)
    if not fee_ids:
        amount = float(payment.get("amount") or payment.get("total") or 0)
        return [{"title": "Fee Payment", "amount": amount}] if amount else []
    client = get_client()
    res = (
        await client.table("fees")
        .select("id,title,amount")
        .eq("school_id", school_id)
        .in_("id", fee_ids)
        .execute()
    )
    rows = res.data or []
    if not rows:
        amount = float(payment.get("amount") or payment.get("total") or 0)
        return [{"title": "Fee Payment", "amount": amount}]
    return [{"title": r.get("title") or "Fee", "amount": float(r.get("amount") or 0)} for r in rows]


def _build_snapshot(
    *,
    school: dict[str, Any],
    student: dict[str, Any],
    payment: dict[str, Any],
    receipt_number: str,
    fee_lines: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    subtotal = round(sum(float(x.get("amount") or 0) for x in fee_lines), 2)
    discount = float(payment.get("discount") or 0)
    fine = float(payment.get("fine") or 0)
    tax = float(payment.get("tax") or 0)
    total_paid = float(payment.get("total") or payment.get("amount") or subtotal)
    return {
        "school": {
            "school_name": school.get("school_name"),
            "address": school.get("address"),
            "city": school.get("city"),
            "state": school.get("state"),
            "pincode": school.get("pincode"),
            "phone": school.get("phone"),
            "email": school.get("email"),
            "website": school.get("website"),
            "logo_url": school.get("logo_url"),
            "gst_number": school.get("gst_number"),
            "institution_code": school.get("institution_code"),
        },
        "student": {
            "full_name": student.get("full_name"),
            "admission_no": student.get("admission_no"),
            "roll_no": student.get("roll_no"),
            "class_name": student.get("class_name"),
            "section_name": student.get("section_name"),
            "email": student.get("email"),
        },
        "receipt": {
            "receipt_number": receipt_number,
            "invoice_number": payment.get("invoice_number"),
            "generated_at": generated_at,
            "receipt_date": generated_at,
        },
        "payment": {
            "payment_status": payment.get("payment_status") or "paid",
            "payment_method": payment.get("payment_method"),
            "gateway_name": payment.get("gateway_name"),
            "gateway_payment_id": payment.get("gateway_payment_id"),
            "gateway_order_id": payment.get("gateway_order_id"),
            "transaction_reference": payment.get("transaction_reference"),
            "payment_date": payment.get("payment_date") or generated_at,
            "currency": payment.get("currency") or "INR",
            "amount": payment.get("amount"),
            "tax": tax,
            "discount": discount,
            "fine": fine,
            "total": total_paid,
            "invoice_number": payment.get("invoice_number"),
        },
        "fee_lines": fee_lines,
        "totals": {
            "subtotal": subtotal,
            "discount": discount,
            "fine": fine,
            "tax": tax,
            "previous_due": 0,
            "total_paid": total_paid,
            "currency": payment.get("currency") or "INR",
        },
    }


def _row_to_out(row: dict[str, Any], extras: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    snap = row.get("snapshot") or {}
    student = snap.get("student") or {}
    payment = snap.get("payment") or {}
    out = {
        "id": row.get("id"),
        "receipt_number": row.get("receipt_number"),
        "school_id": row.get("school_id"),
        "student_id": row.get("student_id"),
        "payment_id": row.get("payment_id"),
        "invoice_number": row.get("invoice_number"),
        "pdf_url": row.get("pdf_url"),
        "generated_at": row.get("generated_at"),
        "generated_by": row.get("generated_by"),
        "created_at": row.get("created_at"),
        "student_name": student.get("full_name"),
        "admission_no": student.get("admission_no"),
        "class_name": student.get("class_name"),
        "section_name": student.get("section_name"),
        "amount_paid": payment.get("total") or payment.get("amount"),
        "payment_status": payment.get("payment_status"),
        "payment_method": payment.get("payment_method"),
        "payment_date": payment.get("payment_date"),
        "currency": payment.get("currency"),
    }
    if extras:
        out.update(extras)
    return out


async def get_existing_for_payment(payment_id: str) -> Optional[dict[str, Any]]:
    client = get_client()
    res = (
        await client.table("fee_receipts")
        .select("*")
        .eq("payment_id", payment_id)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def generate_for_paid_payment(
    payment: dict[str, Any],
    *,
    generated_by: str = "system",
    storage: Optional[ReceiptStorage] = None,
    regenerate: bool = False,
) -> Optional[dict[str, Any]]:
    """Create PDF receipt after a payment is PAID. Idempotent per payment_id.

    Never generates for pending/failed/cancelled/refunded payments.
    Set ``regenerate=True`` to rebuild the PDF while keeping the receipt number.
    """
    store = storage or default_storage
    status_norm = (payment.get("payment_status") or "").lower()
    if status_norm in _TERMINAL_NON_PAID or status_norm != "paid":
        logger.info(
            "skip receipt generation payment=%s status=%s",
            payment.get("id"),
            status_norm,
        )
        return None

    payment_id = payment.get("id")
    school_id = payment.get("school_id")
    if not payment_id or not school_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing payment or school")

    existing = await get_existing_for_payment(payment_id)
    if existing and not regenerate:
        logger.info("receipt already exists for payment=%s", payment_id)
        return existing

    try:
        school = await _load_school(school_id)
        student = await _load_student(
            school_id,
            student_id=payment.get("student_id"),
            student_email=payment.get("student_email"),
        )
        if not student:
            logger.warning("receipt: student missing for payment=%s", payment_id)

        fee_lines = await _load_fee_lines(school_id, payment)
        generated_at = _now()

        if existing:
            receipt_number = existing["receipt_number"]
        elif payment.get("receipt_number") and not str(payment.get("receipt_number")).startswith("RCPT-"):
            receipt_number = payment["receipt_number"]
        else:
            receipt_number = await next_receipt_number(school_id, school)

        snapshot = _build_snapshot(
            school=school,
            student=student,
            payment=payment,
            receipt_number=receipt_number,
            fee_lines=fee_lines,
            generated_at=generated_at,
        )

        pdf_bytes = generate_receipt_pdf(snapshot)
        year = _year_from_iso(generated_at)
        pdf_path, pdf_url = store.save_pdf(
            year=year,
            receipt_number=receipt_number,
            content=pdf_bytes,
        )

        client = get_client()
        if existing:
            updated = (
                await client.table("fee_receipts")
                .update(
                    {
                        "pdf_path": pdf_path,
                        "pdf_url": pdf_url,
                        "snapshot": snapshot,
                        "generated_at": generated_at,
                        "generated_by": generated_by,
                        "invoice_number": payment.get("invoice_number")
                        or existing.get("invoice_number"),
                    }
                )
                .eq("id", existing["id"])
                .execute()
            )
            row = (updated.data or [{**existing, "pdf_path": pdf_path, "pdf_url": pdf_url}])[0]
            logger.info("receipt regenerated number=%s payment=%s", receipt_number, payment_id)
        else:
            row_payload = {
                "receipt_number": receipt_number,
                "school_id": school_id,
                "student_id": student.get("id") or payment.get("student_id"),
                "payment_id": payment_id,
                "invoice_number": payment.get("invoice_number"),
                "pdf_path": pdf_path,
                "pdf_url": pdf_url,
                "snapshot": snapshot,
                "generated_at": generated_at,
                "generated_by": generated_by,
                "created_at": generated_at,
            }
            inserted = await client.table("fee_receipts").insert(row_payload).execute()
            if not inserted.data:
                raise HTTPException(
                    status.HTTP_500_INTERNAL_SERVER_ERROR,
                    "Failed to store receipt record",
                )
            row = inserted.data[0]
            logger.info("receipt generated number=%s payment=%s", receipt_number, payment_id)

        await client.table("fee_payments").update(
            {
                "receipt_number": receipt_number,
                "receipt_url": pdf_url,
                "updated_at": generated_at,
            }
        ).eq("id", payment_id).eq("school_id", school_id).execute()

        return row
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(
            "receipt generation failed payment=%s school=%s: %s",
            payment_id,
            school_id,
            exc,
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Receipt generation failed: {exc}",
        ) from exc


async def ensure_receipt_after_paid(
    payment: dict[str, Any],
    *,
    generated_by: str = "system",
) -> Optional[dict[str, Any]]:
    """Best-effort wrapper used by payment flow — never rolls back a paid payment."""
    try:
        return await generate_for_paid_payment(payment, generated_by=generated_by)
    except Exception as exc:
        logger.exception(
            "ensure_receipt_after_paid failed payment=%s: %s",
            payment.get("id"),
            exc,
        )
        return None


async def list_student_receipts(user: dict) -> list[dict[str, Any]]:
    if user.get("role") != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Students only")
    school_id = user["school_id"]
    client = get_client()
    # Resolve student id
    stu = (
        await client.table("students")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    student_id = (stu.data or [{}])[0].get("id")
    q = (
        client.table("fee_receipts")
        .select("*")
        .eq("school_id", school_id)
        .order("generated_at", desc=True)
    )
    if student_id:
        q = q.eq("student_id", student_id)
    else:
        # Fallback via payment email match — load via payments
        pays = (
            await client.table("fee_payments")
            .select("id")
            .eq("school_id", school_id)
            .eq("student_email", (user.get("email") or "").strip().lower())
            .eq("payment_status", "paid")
            .execute()
        )
        pay_ids = [p["id"] for p in (pays.data or [])]
        if not pay_ids:
            return []
        q = q.in_("payment_id", pay_ids)
    res = await q.execute()
    return [_row_to_out(r) for r in (res.data or [])]


async def get_student_receipt(user: dict, receipt_id: str) -> dict[str, Any]:
    items = await list_student_receipts(user)
    for item in items:
        if item["id"] == receipt_id or item["receipt_number"] == receipt_id:
            return item
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")


async def search_admin_receipts(
    user: dict,
    *,
    student_name: Optional[str] = None,
    admission_no: Optional[str] = None,
    receipt_number: Optional[str] = None,
    class_name: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    payment_status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    role = user.get("role")
    client = get_client()
    q = client.table("fee_receipts").select("*").order("generated_at", desc=True)

    if role != "super_admin":
        school_id = user.get("school_id")
        if not school_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No school scope")
        q = q.eq("school_id", school_id)

    if receipt_number:
        q = q.ilike("receipt_number", f"%{receipt_number.strip()}%")
    if date_from:
        q = q.gte("generated_at", date_from)
    if date_to:
        # inclusive end-of-day if date-only
        end = date_to if "T" in date_to else f"{date_to}T23:59:59.999Z"
        q = q.lte("generated_at", end)

    res = await q.range(offset, offset + limit - 1).execute()
    rows = res.data or []

    # Client-side filters on snapshot fields (Supabase JSON filter support varies)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        out = _row_to_out(row)
        snap = row.get("snapshot") or {}
        student = snap.get("student") or {}
        payment = snap.get("payment") or {}
        if student_name:
            name = (student.get("full_name") or "").lower()
            if student_name.strip().lower() not in name:
                continue
        if admission_no:
            adm = (student.get("admission_no") or "").lower()
            if admission_no.strip().lower() not in adm:
                continue
        if class_name:
            cn = (student.get("class_name") or "").lower()
            if class_name.strip().lower() not in cn:
                continue
        if payment_status:
            ps = (payment.get("payment_status") or "").lower()
            if payment_status.strip().lower() != ps:
                continue
        filtered.append(out)

    return {"items": filtered, "total": len(filtered)}


async def get_admin_receipt(user: dict, receipt_id: str) -> dict[str, Any]:
    client = get_client()
    q = (
        client.table("fee_receipts")
        .select("*")
        .or_(f"id.eq.{receipt_id},receipt_number.eq.{receipt_id}")
        .limit(1)
    )
    if user.get("role") != "super_admin":
        q = q.eq("school_id", user["school_id"])
    res = await q.execute()
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    return res.data[0]


async def download_receipt_pdf(
    user: dict,
    receipt_id: str,
    *,
    as_student: bool = False,
    storage: Optional[ReceiptStorage] = None,
) -> tuple[bytes, str, str]:
    """Returns (pdf_bytes, filename, receipt_number). Enforces access control."""
    store = storage or default_storage
    client = get_client()

    if as_student:
        meta = await get_student_receipt(user, receipt_id)
        res = (
            await client.table("fee_receipts")
            .select("*")
            .eq("id", meta["id"])
            .eq("school_id", user["school_id"])
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
        row = res.data[0]
    else:
        row = await get_admin_receipt(user, receipt_id)

    number = row.get("receipt_number") or "receipt"
    snapshot = row.get("snapshot")
    if isinstance(snapshot, dict) and snapshot:
        # Rebuild from snapshot so currency glyphs (₹) always use current fonts.
        try:
            content = generate_receipt_pdf(snapshot)
            pdf_path = row.get("pdf_path")
            if pdf_path:
                try:
                    year = _year_from_iso(row.get("generated_at"))
                    store.save_pdf(year=year, receipt_number=number, content=content)
                except Exception:
                    pass
            logger.info(
                "receipt downloaded (rebuilt) number=%s by=%s role=%s",
                number,
                user.get("id"),
                user.get("role"),
            )
            return content, f"{number}.pdf", number
        except Exception as exc:
            logger.warning("receipt rebuild failed number=%s: %s", number, exc)

    pdf_path = row.get("pdf_path")
    if not pdf_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt PDF not found")
    try:
        content = store.read_pdf(pdf_path)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt PDF missing on disk") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    logger.info(
        "receipt downloaded number=%s by=%s role=%s",
        number,
        user.get("id"),
        user.get("role"),
    )
    return content, f"{number}.pdf", number


async def regenerate_receipt(
    user: dict,
    receipt_id: str,
    *,
    storage: Optional[ReceiptStorage] = None,
) -> dict[str, Any]:
    row = await get_admin_receipt(user, receipt_id)
    client = get_client()
    pay = (
        await client.table("fee_payments")
        .select("*")
        .eq("id", row["payment_id"])
        .limit(1)
        .execute()
    )
    if not pay.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Linked payment not found")
    payment = pay.data[0]
    if (payment.get("payment_status") or "").lower() != "paid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment is not paid")

    payment = {**payment, "receipt_number": row["receipt_number"]}
    updated = await generate_for_paid_payment(
        payment,
        generated_by=user.get("id") or user.get("email") or "admin",
        storage=storage,
        regenerate=True,
    )
    if not updated:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Regenerate failed")
    logger.info(
        "receipt regenerated number=%s by=%s",
        row.get("receipt_number"),
        user.get("id"),
    )
    return _row_to_out(updated)


async def _fee_payment_for_ledger(
    school_id: str,
    ledger: dict[str, Any],
) -> dict[str, Any]:
    """Find or create a ``fee_payments`` row for a legacy office ``payments`` ledger entry."""
    import uuid

    client = get_client()
    fee_id = str(ledger.get("fee_id") or "") or None
    amount = float(ledger.get("amount") or 0)
    method = (ledger.get("method") or "office").strip().lower() or "office"
    paid_at = ledger.get("paid_at") or ledger.get("created_at") or _now()

    student_email = None
    student_id = None
    if fee_id:
        fee_res = (
            await client.table("fees")
            .select("id,student_email")
            .eq("school_id", school_id)
            .eq("id", fee_id)
            .limit(1)
            .execute()
        )
        fee = (fee_res.data or [{}])[0]
        student_email = (fee.get("student_email") or "").strip().lower() or None

    if student_email:
        user_res = (
            await client.table("users")
            .select("id")
            .eq("school_id", school_id)
            .eq("email", student_email)
            .limit(1)
            .execute()
        )
        if user_res.data:
            stu = (
                await client.table("students")
                .select("id")
                .eq("school_id", school_id)
                .eq("user_id", user_res.data[0]["id"])
                .limit(1)
                .execute()
            )
            if stu.data:
                student_id = stu.data[0].get("id")

    # Prefer an existing fee_payments row that already covers this fee
    if fee_id:
        existing = (
            await client.table("fee_payments")
            .select("*")
            .eq("school_id", school_id)
            .eq("payment_status", "paid")
            .eq("fee_id", fee_id)
            .order("payment_date", desc=True)
            .limit(5)
            .execute()
        )
        for row in existing.data or []:
            return row
        remark_match = (
            await client.table("fee_payments")
            .select("*")
            .eq("school_id", school_id)
            .eq("payment_status", "paid")
            .ilike("remarks", f"%{fee_id}%")
            .order("payment_date", desc=True)
            .limit(10)
            .execute()
        )
        for row in remark_match.data or []:
            remarks = row.get("remarks") or ""
            if remarks.startswith("fees:") and fee_id in remarks[5:].split(","):
                return row

    invoice = f"INV-{uuid.uuid4().hex[:12].upper()}"
    payment_row = {
        "school_id": school_id,
        "student_id": student_id,
        "student_email": student_email,
        "fee_id": fee_id,
        "invoice_number": invoice,
        "amount": round(amount, 2),
        "tax": 0,
        "discount": 0,
        "fine": 0,
        "total": round(amount, 2),
        "currency": "INR",
        "gateway_name": "office",
        "payment_status": "paid",
        "payment_method": method,
        "payment_date": paid_at,
        "remarks": f"fees:{fee_id}" if fee_id else f"ledger:{ledger.get('id')}",
        "created_at": paid_at,
        "updated_at": _now(),
    }
    inserted = await client.table("fee_payments").insert(payment_row).execute()
    fp = (inserted.data or [None])[0]
    if not fp:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not create payment record for receipt",
        )
    return {**payment_row, **fp}


async def ensure_receipt_for_transaction(
    user: dict,
    transaction_id: str,
) -> dict[str, Any]:
    """Ensure a PDF receipt exists for a recent-fees transaction (``fpay-*`` or ``pay-*``).

    Returns receipt fields plus ``transaction_id`` (may upgrade ``pay-*`` → ``fpay-*``).
    """
    school_id = user.get("school_id")
    if not school_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No school scope")

    tid = (transaction_id or "").strip()
    if not tid:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "transaction_id is required")

    client = get_client()
    generated_by = user.get("id") or user.get("email") or "admin"
    payment: Optional[dict[str, Any]] = None
    out_tx_id = tid

    if tid.startswith("fpay-"):
        payment_id = tid[5:]
        res = (
            await client.table("fee_payments")
            .select("*")
            .eq("id", payment_id)
            .eq("school_id", school_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
        payment = res.data[0]
    elif tid.startswith("pay-"):
        ledger_id = tid[4:]
        led = (
            await client.table("payments")
            .select("*")
            .eq("id", ledger_id)
            .eq("school_id", school_id)
            .limit(1)
            .execute()
        )
        if not led.data:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
        payment = await _fee_payment_for_ledger(school_id, led.data[0])
        out_tx_id = f"fpay-{payment['id']}"
    else:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Unsupported transaction id. Use a paid Fees paid / Custom pay entry.",
        )

    if (payment.get("payment_status") or "").lower() != "paid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment is not paid")

    row = await generate_for_paid_payment(payment, generated_by=generated_by)
    if not row:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "Could not generate receipt for this payment",
        )

    out = _row_to_out(row)
    out["transaction_id"] = out_tx_id
    return out
