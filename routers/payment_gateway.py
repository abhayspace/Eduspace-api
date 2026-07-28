"""School payment gateway admin + student payment + webhook APIs."""
from __future__ import annotations

import json
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from schemas.payment import CreateFeeOrderIn, PaymentGatewayUpsertIn, VerifyFeePaymentIn
from services.payment import gateway_service, payment_service
from utils.deps import current_user, require_roles

router = APIRouter(tags=["payment-gateway"])

_FEE_ADMIN = require_roles(
    "school_admin", "office_staff", "principal", "vice_principal", "super_admin"
)


# ---------------------------------------------------------------------------
# Admin — /api/payment-gateway
# ---------------------------------------------------------------------------


@router.get("/payment-gateway")
async def get_payment_gateway(user: dict = Depends(_FEE_ADMIN)) -> dict:
    return await gateway_service.get_gateway_public(user["school_id"])


@router.post("/payment-gateway")
async def save_payment_gateway(
    body: PaymentGatewayUpsertIn,
    user: dict = Depends(_FEE_ADMIN),
) -> dict:
    row = await gateway_service.upsert_gateway(
        user["school_id"], body.model_dump(), replace_secrets=True
    )
    return {"ok": True, "gateway": row}


@router.put("/payment-gateway")
async def update_payment_gateway(
    body: PaymentGatewayUpsertIn,
    user: dict = Depends(_FEE_ADMIN),
) -> dict:
    row = await gateway_service.upsert_gateway(
        user["school_id"], body.model_dump(), replace_secrets=False
    )
    return {"ok": True, "gateway": row}


@router.delete("/payment-gateway")
async def disable_payment_gateway(user: dict = Depends(_FEE_ADMIN)) -> dict:
    return await gateway_service.disable_gateway(user["school_id"])


@router.post("/payment-gateway/test")
async def test_payment_gateway(user: dict = Depends(_FEE_ADMIN)) -> dict:
    return await gateway_service.test_gateway(user["school_id"])


@router.get("/payment-gateway/history")
async def payment_history(
    user: dict = Depends(_FEE_ADMIN),
    student_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    rows = await payment_service.list_payment_history(
        user["school_id"], student_id=student_id, limit=limit
    )
    return {"items": rows}


# ---------------------------------------------------------------------------
# Student — /api/student/fees/*
# ---------------------------------------------------------------------------


@router.get("/student/fees")
async def student_fees_summary(user: dict = Depends(current_user)) -> dict:
    from database import get_client

    if user.get("role") != "student":
        return {
            "pending": [],
            "paid": [],
            "fine": 0,
            "discount": 0,
            "grand_total": 0,
        }
    client = get_client()
    res = (
        await client.table("fees")
        .select("id,title,amount,due_date,status,paid_at")
        .eq("school_id", user["school_id"])
        .eq("student_email", user["email"])
        .order("due_date")
        .limit(200)
        .execute()
    )
    rows = res.data or []
    pending = [r for r in rows if r.get("status") == "pending"]
    paid = [r for r in rows if r.get("status") == "paid"]
    fine = 0.0
    discount = 0.0
    grand_total = round(sum(float(r.get("amount") or 0) for r in pending) + fine - discount, 2)
    return {
        "pending": pending,
        "paid": paid,
        "fine": fine,
        "discount": discount,
        "grand_total": grand_total,
    }


@router.post("/student/fees/create-order")
async def student_create_order(
    body: CreateFeeOrderIn,
    user: dict = Depends(current_user),
) -> dict:
    return await payment_service.create_student_order(
        user, fee_ids=body.fee_ids, amount=body.amount
    )


@router.post("/student/fees/verify-payment")
async def student_verify_payment(
    body: VerifyFeePaymentIn,
    user: dict = Depends(current_user),
) -> dict:
    return await payment_service.verify_student_payment(
        user,
        gateway_order_id=body.gateway_order_id,
        gateway_payment_id=body.gateway_payment_id,
        signature=body.signature,
        raw=body.raw,
        gateway_hint=body.gateway,
    )


@router.get("/student/fees/order/{order_id}/status")
async def student_order_status(order_id: str, user: dict = Depends(current_user)) -> dict:
    """Server-side status check — never mark paid from the client alone."""
    return await payment_service.refresh_order_status(user, order_id)


@router.get("/student/fees/history")
async def student_fee_history(user: dict = Depends(current_user)) -> dict:
    from database import get_client

    client = get_client()
    student_id = None
    if user.get("role") == "student":
        res = (
            await client.table("students")
            .select("id")
            .eq("school_id", user["school_id"])
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        student_id = (res.data or [{}])[0].get("id") if res.data else None
    rows = await payment_service.list_payment_history(
        user["school_id"], student_id=student_id, limit=50
    )
    return {"items": rows}


@router.get("/student/fees/receipt/{receipt_id}")
async def student_fee_receipt(receipt_id: str, user: dict = Depends(current_user)) -> dict:
    return await payment_service.get_receipt(user["school_id"], receipt_id)


# ---------------------------------------------------------------------------
# Webhooks — /api/payment/webhook/{gateway}
# ---------------------------------------------------------------------------


async def _webhook(gateway: str, request: Request) -> dict:
    body = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    payload: dict[str, Any]
    try:
        payload = json.loads(body.decode("utf-8") or "{}")
    except Exception:
        # PayU often posts form-encoded
        form = await request.form()
        payload = {k: form.get(k) for k in form.keys()}
    school_id = request.query_params.get("school_id")
    return await payment_service.process_webhook(
        gateway,
        headers=headers,
        body=body,
        payload=payload,
        school_id=school_id,
    )


@router.post("/payment/webhook/razorpay")
async def webhook_razorpay(request: Request) -> dict:
    return await _webhook("razorpay", request)


@router.post("/payment/webhook/phonepe")
async def webhook_phonepe(request: Request) -> dict:
    return await _webhook("phonepe", request)


@router.post("/payment/webhook/cashfree")
async def webhook_cashfree(request: Request) -> dict:
    return await _webhook("cashfree", request)


@router.post("/payment/webhook/payu")
async def webhook_payu(request: Request) -> dict:
    return await _webhook("payu", request)


@router.post("/payment/webhook/other")
async def webhook_other(request: Request) -> dict:
    return await _webhook("other", request)
