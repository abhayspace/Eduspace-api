"""Fee payment orders, signature verification, and webhook processing.

Never trust the mobile client to mark a fee as paid. Status changes to PAID
only after gateway signature verification or a verified webhook, with amount
and currency checks.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status

from database import get_client
from services.payment.gateway_base import CreateOrderRequest, VerifyPaymentRequest
from services.payment import gateway_service

logger = logging.getLogger("eduspace.payment")

_AMOUNT_TOLERANCE = 0.05  # INR rupees


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _receipt_number(school_id: str) -> str:
    return f"RCPT-{school_id[:8].upper()}-{uuid.uuid4().hex[:8].upper()}"


def _fee_ids_from_payment(payment: dict[str, Any]) -> list[str]:
    remarks = payment.get("remarks") or ""
    if remarks.startswith("fees:"):
        return [x for x in remarks[5:].split(",") if x]
    if payment.get("fee_id"):
        return [str(payment["fee_id"])]
    return []


async def _log_event(
    school_id: Optional[str],
    gateway_name: Optional[str],
    event_type: str,
    payload: dict[str, Any],
    *,
    dedupe_key: Optional[str] = None,
) -> bool:
    """Insert audit row. Returns False if duplicate (dedupe_key already seen)."""
    client = get_client()
    if dedupe_key:
        existing = (
            await client.table("payment_events")
            .select("id")
            .eq("school_id", school_id)
            .eq("event_type", event_type)
            .contains("payload", {"dedupe_key": dedupe_key})
            .limit(1)
            .execute()
        )
        if existing.data:
            logger.info("duplicate payment event ignored: %s %s", event_type, dedupe_key)
            return False

    body = dict(payload)
    if dedupe_key:
        body["dedupe_key"] = dedupe_key
    try:
        await client.table("payment_events").insert(
            {
                "school_id": school_id,
                "gateway_name": gateway_name,
                "event_type": event_type,
                "payload": body,
            }
        ).execute()
    except Exception as exc:
        logger.warning("payment event log failed: %s", exc)
    return True


async def _resolve_student(school_id: str, user: dict) -> tuple[Optional[str], str]:
    email = user.get("email") or ""
    client = get_client()
    res = (
        await client.table("students")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", user["id"])
        .limit(1)
        .execute()
    )
    student_id = (res.data or [{}])[0].get("id") if res.data else None
    return student_id, email


def _amounts_match(expected: float, actual: Optional[float]) -> bool:
    if actual is None:
        return True  # gateway did not return amount; rely on signature
    return abs(float(expected) - float(actual)) <= _AMOUNT_TOLERANCE


async def create_student_order(
    user: dict,
    *,
    fee_ids: list[str],
    amount: Optional[float] = None,
) -> dict[str, Any]:
    school_id = user["school_id"]
    if user.get("role") != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students can create fee orders")

    client = get_client()
    if not fee_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "fee_ids required")

    fees_res = (
        await client.table("fees")
        .select("id,title,amount,status,student_email")
        .eq("school_id", school_id)
        .eq("student_email", user["email"])
        .in_("id", fee_ids)
        .execute()
    )
    fees = fees_res.data or []
    if len(fees) != len(fee_ids):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "One or more fees not found")
    pending = [f for f in fees if f.get("status") == "pending"]
    if not pending:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No pending fees to pay")

    total = round(sum(float(f.get("amount") or 0) for f in pending), 2)
    if amount is not None and abs(float(amount) - total) > 0.01:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Amount mismatch with pending fees")

    gateway, gw_row = await gateway_service.load_gateway_for_school(school_id)
    student_id, email = await _resolve_student(school_id, user)
    invoice = f"INV-{uuid.uuid4().hex[:12].upper()}"
    currency = (gw_row.get("currency") or "INR").upper()

    order = await gateway.create_order(
        CreateOrderRequest(
            amount=total,
            currency=currency,
            receipt=invoice,
            student_email=email,
            student_name=user.get("full_name"),
            notes={"school_id": school_id, "fee_ids": ",".join(fee_ids), "invoice": invoice},
        )
    )

    payment_row = {
        "school_id": school_id,
        "student_id": student_id,
        "student_email": email,
        "fee_id": pending[0]["id"] if len(pending) == 1 else None,
        "invoice_number": invoice,
        "amount": total,
        "tax": 0,
        "discount": 0,
        "fine": 0,
        "total": total,
        "currency": order.currency or currency,
        "gateway_name": order.gateway_name,
        "gateway_order_id": order.order_id,
        "payment_status": "pending",
        "remarks": f"fees:{','.join(f['id'] for f in pending)}",
        "created_at": _now(),
        "updated_at": _now(),
    }
    inserted = await client.table("fee_payments").insert(payment_row).execute()
    row = (inserted.data or [payment_row])[0]

    await _log_event(
        school_id,
        order.gateway_name,
        "order_created",
        {"order_id": order.order_id, "total": total, "currency": currency, "fee_ids": fee_ids},
    )
    logger.info(
        "fee order created school=%s order=%s amount=%s gateway=%s",
        school_id,
        order.order_id,
        total,
        order.gateway_name,
    )

    checkout = dict(order.checkout_payload or {})
    public_key = (
        checkout.get("key")
        or checkout.get("public_key")
        or checkout.get("appId")
        or gw_row.get("key_id")
        or gw_row.get("client_id")
    )

    return {
        "gateway": order.gateway_name,
        "order_id": order.order_id,
        "amount": total,
        "currency": order.currency or currency,
        "public_key": public_key,
        "payment_id": row.get("id"),
        "invoice_number": invoice,
        "gateway_name": order.gateway_name,
        "gateway_order_id": order.order_id,
        "checkout": checkout,
    }


async def verify_student_payment(
    user: dict,
    *,
    gateway_order_id: str,
    gateway_payment_id: Optional[str] = None,
    signature: Optional[str] = None,
    raw: Optional[dict[str, Any]] = None,
    gateway_hint: Optional[str] = None,
) -> dict[str, Any]:
    """Verify client-returned payment credentials via gateway signature.

    The client may send payment_id + signature; the backend still verifies
    with the school secret and amount before marking PAID.
    """
    school_id = user["school_id"]
    client = get_client()
    pay_res = (
        await client.table("fee_payments")
        .select("*")
        .eq("school_id", school_id)
        .eq("gateway_order_id", gateway_order_id)
        .limit(1)
        .execute()
    )
    if not pay_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment order not found")
    payment = pay_res.data[0]

    if payment.get("student_email") and payment["student_email"] != user.get("email"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your payment order")

    if (payment.get("payment_status") or "").lower() == "paid":
        return {"ok": True, "already_paid": True, "payment": _public_payment(payment)}

    await _log_event(
        school_id,
        payment.get("gateway_name") or gateway_hint,
        "verify_attempt",
        {
            "order_id": gateway_order_id,
            "payment_id": gateway_payment_id,
            "has_signature": bool(signature),
        },
    )

    gateway, gw_row = await gateway_service.load_gateway_for_school(school_id)
    expected_currency = (payment.get("currency") or gw_row.get("currency") or "INR").upper()

    result = await gateway.verify_payment(
        VerifyPaymentRequest(
            order_id=gateway_order_id,
            payment_id=gateway_payment_id,
            signature=signature,
            raw=raw or {},
        )
    )

    if not result.success:
        await _mark_failed(payment, reason=result.message or "verification_failed")
        await _log_event(
            school_id,
            payment.get("gateway_name"),
            "verify_failed",
            {"order_id": gateway_order_id, "message": result.message},
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            result.message or "Payment verification failed",
        )

    if result.amount is not None and not _amounts_match(
        float(payment.get("total") or payment.get("amount") or 0),
        result.amount,
    ):
        await _mark_failed(payment, reason="amount_mismatch")
        await _log_event(
            school_id,
            payment.get("gateway_name"),
            "verify_amount_mismatch",
            {
                "order_id": gateway_order_id,
                "expected": payment.get("total"),
                "actual": result.amount,
            },
        )
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment amount does not match order")

    raw_currency = (result.raw or {}).get("currency")
    if raw_currency and str(raw_currency).upper() != expected_currency:
        await _mark_failed(payment, reason="currency_mismatch")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment currency does not match order")

    return await _mark_paid(
        payment,
        gateway_payment_id=result.payment_id or gateway_payment_id,
        method=result.method,
        event_payload={"verify": result.raw or {}, "via": "client_signature"},
        verified_via="signature",
    )


async def refresh_order_status(user: dict, gateway_order_id: str) -> dict[str, Any]:
    """Server-side poll: ask the gateway if the order was captured (no client trust)."""
    school_id = user["school_id"]
    client = get_client()
    pay_res = (
        await client.table("fee_payments")
        .select("*")
        .eq("school_id", school_id)
        .eq("gateway_order_id", gateway_order_id)
        .limit(1)
        .execute()
    )
    if not pay_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment order not found")
    payment = pay_res.data[0]

    if payment.get("student_email") and payment["student_email"] != user.get("email"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your payment order")

    if (payment.get("payment_status") or "").lower() == "paid":
        return {"ok": True, "already_paid": True, "payment": _public_payment(payment)}

    gateway, _ = await gateway_service.load_gateway_for_school(school_id)
    fetcher = getattr(gateway, "fetch_order_payment", None)
    if not callable(fetcher):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "This gateway does not support order status refresh; wait for webhook or verify with signature",
        )

    result = await fetcher(gateway_order_id)
    await _log_event(
        school_id,
        payment.get("gateway_name"),
        "status_refresh",
        {"order_id": gateway_order_id, "success": result.success, "message": result.message},
    )

    if not result.success:
        return {
            "ok": False,
            "pending": True,
            "message": result.message or "Payment not captured yet",
            "payment": _public_payment(payment),
        }

    if result.amount is not None and not _amounts_match(
        float(payment.get("total") or payment.get("amount") or 0),
        result.amount,
    ):
        await _mark_failed(payment, reason="amount_mismatch")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment amount does not match order")

    return await _mark_paid(
        payment,
        gateway_payment_id=result.payment_id,
        method=result.method,
        event_payload={"refresh": result.raw or {}, "via": "gateway_fetch"},
        verified_via="gateway_fetch",
    )


async def _mark_failed(payment: dict[str, Any], *, reason: str) -> None:
    if (payment.get("payment_status") or "").lower() == "paid":
        return
    client = get_client()
    await (
        client.table("fee_payments")
        .update(
            {
                "payment_status": "failed",
                "remarks": f"{payment.get('remarks') or ''}|fail:{reason}"[:500],
                "updated_at": _now(),
            }
        )
        .eq("id", payment["id"])
        .eq("school_id", payment["school_id"])
        .execute()
    )


async def _mark_paid(
    payment: dict[str, Any],
    *,
    gateway_payment_id: Optional[str],
    method: Optional[str],
    event_payload: Optional[dict[str, Any]] = None,
    verified_via: str = "unknown",
) -> dict[str, Any]:
    client = get_client()
    school_id = payment["school_id"]
    now = _now()
    receipt = payment.get("receipt_number") or _receipt_number(school_id)

    if (payment.get("payment_status") or "").lower() == "paid":
        try:
            from services.receipt.receipt_service import (
                ensure_receipt_after_paid,
                get_existing_for_payment,
            )

            existing = await get_existing_for_payment(payment["id"])
            if not existing:
                receipt_row = await ensure_receipt_after_paid(payment, generated_by="system")
                if receipt_row:
                    payment = {
                        **payment,
                        "receipt_number": receipt_row.get("receipt_number"),
                        "receipt_url": receipt_row.get("pdf_url"),
                    }
        except Exception as exc:
            logger.warning("receipt backfill on already_paid failed: %s", exc)
        return {"ok": True, "already_paid": True, "payment": _public_payment(payment)}

    # Reject duplicate gateway payment IDs on another row
    if gateway_payment_id:
        dup = (
            await client.table("fee_payments")
            .select("id,payment_status")
            .eq("school_id", school_id)
            .eq("gateway_payment_id", gateway_payment_id)
            .neq("id", payment["id"])
            .limit(1)
            .execute()
        )
        if dup.data:
            logger.warning(
                "duplicate gateway_payment_id=%s school=%s",
                gateway_payment_id,
                school_id,
            )
            return {"ok": True, "already_paid": True, "payment": _public_payment(payment)}

    update_fields: dict[str, Any] = {
        "payment_status": "paid",
        "gateway_payment_id": gateway_payment_id,
        "transaction_reference": gateway_payment_id,
        "payment_method": method,
        "payment_date": now,
        "receipt_number": receipt,
        "verified_via": verified_via,
        "updated_at": now,
    }
    if event_payload is not None:
        update_fields["event_payload"] = event_payload

    updated = (
        await client.table("fee_payments")
        .update(update_fields)
        .eq("id", payment["id"])
        .eq("school_id", school_id)
        .neq("payment_status", "paid")
        .execute()
    )
    # Another concurrent request may have won
    if not updated.data:
        refreshed = (
            await client.table("fee_payments")
            .select("*")
            .eq("id", payment["id"])
            .limit(1)
            .execute()
        )
        row = (refreshed.data or [payment])[0]
        return {"ok": True, "already_paid": True, "payment": _public_payment(row)}

    row = updated.data[0]

    fee_ids = _fee_ids_from_payment(payment)
    paid_amount = float(payment.get("total") or payment.get("amount") or 0)

    for fee_id in fee_ids:
        fee_q = (
            client.table("fees")
            .update({"status": "paid", "paid_at": now})
            .eq("id", fee_id)
            .eq("school_id", school_id)
            .eq("status", "pending")
        )
        if payment.get("student_email"):
            fee_q = fee_q.eq("student_email", payment["student_email"])
        await fee_q.execute()

    try:
        await client.table("payments").insert(
            {
                "school_id": school_id,
                "fee_id": fee_ids[0] if fee_ids else None,
                "amount": paid_amount,
                "method": method or payment.get("gateway_name") or "gateway",
                "paid_at": now,
            }
        ).execute()
    except Exception as exc:
        logger.warning("payments ledger insert failed: %s", exc)

    await _log_event(
        school_id,
        payment.get("gateway_name"),
        "payment_paid",
        {
            "order_id": payment.get("gateway_order_id"),
            "payment_id": gateway_payment_id,
            "receipt": receipt,
            "verified_via": verified_via,
            "amount": paid_amount,
        },
        dedupe_key=f"paid:{gateway_payment_id or payment.get('gateway_order_id')}",
    )
    logger.info(
        "fee payment PAID school=%s order=%s payment=%s via=%s",
        school_id,
        payment.get("gateway_order_id"),
        gateway_payment_id,
        verified_via,
    )

    paid_row = {**payment, **row, "payment_status": "paid"}
    try:
        from services.receipt.receipt_service import ensure_receipt_after_paid

        receipt_row = await ensure_receipt_after_paid(paid_row, generated_by="system")
        if receipt_row:
            paid_row["receipt_number"] = receipt_row.get("receipt_number") or paid_row.get(
                "receipt_number"
            )
            paid_row["receipt_url"] = receipt_row.get("pdf_url")
    except Exception as exc:
        logger.exception("receipt hook failed after PAID payment=%s: %s", payment.get("id"), exc)

    return {"ok": True, "already_paid": False, "payment": _public_payment(paid_row)}


async def _mark_refunded(
    payment: dict[str, Any],
    *,
    gateway_payment_id: Optional[str],
    event_payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    client = get_client()
    now = _now()
    fields: dict[str, Any] = {
        "payment_status": "refunded",
        "updated_at": now,
    }
    if gateway_payment_id:
        fields["gateway_payment_id"] = gateway_payment_id
        fields["transaction_reference"] = gateway_payment_id
    if event_payload is not None:
        fields["event_payload"] = event_payload

    updated = (
        await client.table("fee_payments")
        .update(fields)
        .eq("id", payment["id"])
        .eq("school_id", payment["school_id"])
        .execute()
    )
    row = (updated.data or [{}])[0] or payment

    # Re-open linked fees as pending so outstanding balance returns
    for fee_id in _fee_ids_from_payment(payment):
        await (
            client.table("fees")
            .update({"status": "pending", "paid_at": None})
            .eq("id", fee_id)
            .eq("school_id", payment["school_id"])
            .eq("status", "paid")
            .execute()
        )

    await _log_event(
        payment["school_id"],
        payment.get("gateway_name"),
        "payment_refunded",
        {"order_id": payment.get("gateway_order_id"), "payment_id": gateway_payment_id},
        dedupe_key=f"refund:{gateway_payment_id or payment.get('gateway_order_id')}",
    )
    return {"ok": True, "status": "refunded", "payment": _public_payment({**payment, **row})}


def _public_payment(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "invoice_number": row.get("invoice_number"),
        "amount": row.get("amount"),
        "total": row.get("total"),
        "currency": row.get("currency") or "INR",
        "gateway_name": row.get("gateway_name"),
        "gateway_order_id": row.get("gateway_order_id"),
        "gateway_payment_id": row.get("gateway_payment_id"),
        "payment_status": row.get("payment_status"),
        "payment_method": row.get("payment_method"),
        "payment_date": row.get("payment_date"),
        "receipt_number": row.get("receipt_number"),
        "receipt_url": row.get("receipt_url"),
        "verified_via": row.get("verified_via"),
    }


def _extract_order_hint(payload: dict[str, Any]) -> Optional[str]:
    entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    notes = entity.get("notes") if isinstance(entity.get("notes"), dict) else {}
    return (
        payload.get("order_id")
        or entity.get("order_id")
        or notes.get("razorpay_order_id")
        or (payload.get("data") or {}).get("order", {}).get("order_id")
        or payload.get("txnid")
        or payload.get("merchantTransactionId")
        or ((payload.get("payload") or {}).get("order") or {}).get("entity", {}).get("id")
    )


def _extract_payment_hint(payload: dict[str, Any]) -> Optional[str]:
    entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
    return (
        payload.get("payment_id")
        or entity.get("id")
        or (payload.get("data") or {}).get("payment", {}).get("cf_payment_id")
        or payload.get("mihpayid")
    )


async def process_webhook(
    gateway_name: str,
    *,
    headers: dict[str, str],
    body: bytes,
    payload: dict[str, Any],
    school_id: Optional[str] = None,
) -> dict[str, Any]:
    client = get_client()
    order_hint = _extract_order_hint(payload)
    payment_hint = _extract_payment_hint(payload)
    gateway_name = gateway_name.lower()

    payment = None
    if order_hint:
        q = (
            client.table("fee_payments")
            .select("*")
            .eq("gateway_order_id", str(order_hint))
            .eq("gateway_name", gateway_name)
            .limit(1)
        )
        if school_id:
            q = q.eq("school_id", school_id)
        res = await q.execute()
        payment = (res.data or [None])[0]

    if not payment and payment_hint:
        q = (
            client.table("fee_payments")
            .select("*")
            .eq("gateway_payment_id", str(payment_hint))
            .eq("gateway_name", gateway_name)
            .limit(1)
        )
        if school_id:
            q = q.eq("school_id", school_id)
        res = await q.execute()
        payment = (res.data or [None])[0]

    # Payment-link flow: match invoice / reference from notes
    if not payment:
        entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
        notes = entity.get("notes") if isinstance(entity.get("notes"), dict) else {}
        invoice = notes.get("invoice") or payload.get("reference_id")
        if invoice:
            q = (
                client.table("fee_payments")
                .select("*")
                .eq("invoice_number", str(invoice))
                .eq("gateway_name", gateway_name)
                .limit(1)
            )
            if school_id:
                q = q.eq("school_id", school_id)
            res = await q.execute()
            payment = (res.data or [None])[0]

    if not payment:
        await _log_event(school_id, gateway_name, "webhook_orphan", {"payload": payload})
        # Acknowledge so gateways do not retry forever for unknown orders
        return {"ok": True, "ignored": True, "reason": "order not found"}

    school_id = payment["school_id"]
    event_name = payload.get("event") or payload.get("type") or "webhook"
    event_id = (
        headers.get("x-razorpay-event-id")
        or headers.get("x-webhook-id")
        or payload.get("id")
        or f"{event_name}:{order_hint}:{payment_hint}"
    )

    is_new = await _log_event(
        school_id,
        gateway_name,
        "webhook_received",
        {"event": event_name, "order_id": order_hint, "payment_id": payment_hint},
        dedupe_key=str(event_id),
    )
    if not is_new:
        return {"ok": True, "duplicate": True}

    gateway, _ = await gateway_service.load_gateway_for_school(school_id)
    result = await gateway.verify_webhook(headers, body, payload)
    if not result.success:
        logger.warning(
            "webhook signature failed school=%s gateway=%s msg=%s",
            school_id,
            gateway_name,
            result.message,
        )
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            result.message or "Webhook verification failed",
        )

    status_norm = (result.status or "").lower()
    # Map common event names if adapter left status pending
    if status_norm in ("", "pending"):
        if event_name in ("payment.captured", "order.paid", "PAYMENT_SUCCESS"):
            status_norm = "paid"
        elif event_name in ("payment.failed", "PAYMENT_ERROR", "PAYMENT_DECLINED"):
            status_norm = "failed"
        elif event_name in ("payment.refunded", "refund.processed", "PAYMENT_REFUNDED"):
            status_norm = "refunded"

    if status_norm == "paid":
        if result.amount is not None and not _amounts_match(
            float(payment.get("total") or payment.get("amount") or 0),
            result.amount,
        ):
            await _mark_failed(payment, reason="webhook_amount_mismatch")
            await _log_event(
                school_id,
                gateway_name,
                "webhook_amount_mismatch",
                {"expected": payment.get("total"), "actual": result.amount},
            )
            return {"ok": False, "reason": "amount_mismatch"}

        return await _mark_paid(
            payment,
            gateway_payment_id=result.payment_id or payment_hint,
            method=result.method or gateway_name,
            event_payload={"webhook": result.raw or payload, "event": event_name},
            verified_via="webhook",
        )

    if status_norm == "failed":
        await _mark_failed(payment, reason="webhook_failed")
        return {"ok": True, "status": "failed"}

    if status_norm == "refunded":
        return await _mark_refunded(
            payment,
            gateway_payment_id=result.payment_id or payment_hint,
            event_payload={"webhook": result.raw or payload, "event": event_name},
        )

    return {"ok": True, "status": status_norm or "ignored"}


async def list_payment_history(school_id: str, *, student_id: Optional[str] = None, limit: int = 50):
    client = get_client()
    q = (
        client.table("fee_payments")
        .select("*")
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .limit(limit)
    )
    if student_id:
        q = q.eq("student_id", student_id)
    res = await q.execute()
    return [_public_payment(row) for row in (res.data or [])]


async def get_receipt(school_id: str, receipt_id: str) -> dict[str, Any]:
    client = get_client()
    res = (
        await client.table("fee_payments")
        .select("*")
        .eq("school_id", school_id)
        .or_(f"id.eq.{receipt_id},receipt_number.eq.{receipt_id}")
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Receipt not found")
    row = res.data[0]
    if row.get("payment_status") != "paid":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment not completed")
    return _public_payment(row)
