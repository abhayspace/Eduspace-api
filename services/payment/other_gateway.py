"""Generic / custom payment gateway adapter for "Other"."""
from __future__ import annotations

import uuid
from typing import Any, Optional

from services.payment.gateway_base import (
    CreateOrderRequest,
    CreateOrderResult,
    PaymentGateway,
    RefundResult,
    VerifyPaymentRequest,
    VerifyPaymentResult,
    WebhookResult,
)


class OtherGateway(PaymentGateway):
    """Placeholder provider for schools using a custom or unlisted gateway."""

    name = "other"

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResult:
        order_id = f"OT_{uuid.uuid4().hex[:24]}"
        return CreateOrderResult(
            order_id=order_id,
            amount=request.amount,
            currency=request.currency or self.credentials.currency or "INR",
            gateway_name=self.name,
            checkout_payload={
                "order_id": order_id,
                "amount": request.amount,
                "currency": request.currency or "INR",
                "merchant_id": self.credentials.merchant_id,
                "key_id": self.credentials.key_id,
                "manual": True,
                "message": "Complete payment with your school's custom gateway.",
            },
            raw={"provider": "other"},
        )

    async def verify_payment(self, request: VerifyPaymentRequest) -> VerifyPaymentResult:
        payment_id = request.payment_id or request.raw.get("payment_id")
        if not payment_id:
            return VerifyPaymentResult(
                success=False,
                order_id=request.order_id,
                message="payment_id required for Other gateway verification",
            )
        return VerifyPaymentResult(
            success=True,
            order_id=request.order_id,
            payment_id=str(payment_id),
            method=request.raw.get("method") or "other",
            message="Marked verified (custom gateway)",
            raw=request.raw,
        )

    async def verify_webhook(
        self, headers: dict[str, str], body: bytes, payload: dict[str, Any]
    ) -> WebhookResult:
        order_id = str(payload.get("order_id") or payload.get("gateway_order_id") or "")
        payment_id = str(payload.get("payment_id") or payload.get("gateway_payment_id") or "") or None
        status_raw = str(payload.get("status") or "paid").lower()
        status = "paid" if status_raw in ("paid", "success", "captured") else "pending"
        if status_raw in ("failed", "cancelled", "canceled"):
            status = "failed"
        return WebhookResult(
            success=True,
            order_id=order_id or None,
            payment_id=payment_id,
            status=status,
            amount=payload.get("amount"),
            method=payload.get("method") or "other",
            message="other webhook accepted",
            raw=payload,
        )

    async def refund_payment(
        self, payment_id: str, amount: Optional[float] = None
    ) -> RefundResult:
        return RefundResult(success=False, message="Refunds for Other gateway are manual")

    async def get_payment_status(self, payment_id: str) -> VerifyPaymentResult:
        return VerifyPaymentResult(
            success=False,
            order_id=payment_id,
            message="Status checks for Other gateway are handled externally",
        )

    async def test_connection(self) -> tuple[bool, str]:
        if not (self.credentials.key_id or self.credentials.merchant_id or self.credentials.client_id):
            return False, "Add at least one merchant / key field for Other gateway"
        return True, "Other gateway credentials saved (manual integration)"
