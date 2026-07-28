"""PayU payment gateway adapter (order token + hash verify)."""
from __future__ import annotations

import hashlib
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


class PayUGateway(PaymentGateway):
    name = "payu"

    def _key_salt(self) -> tuple[str, str]:
        return self.credentials.key_id or "", self.credentials.salt_key or self.credentials.key_secret or ""

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResult:
        key, salt = self._key_salt()
        if not key or not salt:
            raise ValueError("PayU key_id and salt_key are required")
        order_id = f"PU_{uuid.uuid4().hex[:24]}"
        amount = f"{float(request.amount):.2f}"
        product = "School Fees"
        firstname = (request.student_name or "Student").split(" ")[0]
        email = request.student_email or "student@eduspace.local"
        # hash = key|txnid|amount|productinfo|firstname|email|||||||||||salt
        hash_str = f"{key}|{order_id}|{amount}|{product}|{firstname}|{email}|||||||||||{salt}"
        hash_value = hashlib.sha512(hash_str.encode("utf-8")).hexdigest()
        base = (
            "https://test.payu.in/_payment"
            if self.credentials.is_sandbox
            else "https://secure.payu.in/_payment"
        )
        return CreateOrderResult(
            order_id=order_id,
            amount=request.amount,
            currency=request.currency or "INR",
            gateway_name=self.name,
            checkout_payload={
                "action": base,
                "key": key,
                "txnid": order_id,
                "amount": amount,
                "productinfo": product,
                "firstname": firstname,
                "email": email,
                "hash": hash_value,
                "surl": request.callback_url or "",
                "furl": request.callback_url or "",
            },
            raw={"hash_formula": "key|txnid|amount|productinfo|firstname|email|||||||||||salt"},
        )

    async def verify_payment(self, request: VerifyPaymentRequest) -> VerifyPaymentResult:
        key, salt = self._key_salt()
        status = (request.raw.get("status") or "").lower()
        amount = request.raw.get("amount")
        product = request.raw.get("productinfo") or "School Fees"
        firstname = request.raw.get("firstname") or ""
        email = request.raw.get("email") or ""
        provided = request.signature or request.raw.get("hash") or ""
        # reverse hash: salt|status|||||||||||email|firstname|productinfo|amount|txnid|key
        reverse = f"{salt}|{status}|||||||||||{email}|{firstname}|{product}|{amount}|{request.order_id}|{key}"
        expected = hashlib.sha512(reverse.encode("utf-8")).hexdigest()
        ok = bool(provided) and hmac_compare(expected, provided) and status == "success"
        return VerifyPaymentResult(
            success=ok,
            order_id=request.order_id,
            payment_id=request.payment_id or request.raw.get("mihpayid"),
            amount=float(amount) if amount is not None else None,
            message="verified" if ok else "invalid PayU hash/status",
            raw=request.raw,
        )

    async def verify_webhook(
        self, headers: dict[str, str], body: bytes, payload: dict[str, Any]
    ) -> WebhookResult:
        result = await self.verify_payment(
            VerifyPaymentRequest(
                order_id=str(payload.get("txnid") or ""),
                payment_id=str(payload.get("mihpayid") or "") or None,
                signature=str(payload.get("hash") or "") or None,
                raw=payload,
            )
        )
        return WebhookResult(
            success=result.success,
            order_id=result.order_id,
            payment_id=result.payment_id,
            status="paid" if result.success else "failed",
            amount=result.amount,
            message=result.message,
            raw=payload,
        )

    async def refund_payment(
        self, payment_id: str, amount: Optional[float] = None
    ) -> RefundResult:
        return RefundResult(success=False, message="PayU refund not configured")

    async def get_payment_status(self, payment_id: str) -> VerifyPaymentResult:
        return VerifyPaymentResult(
            success=False,
            order_id=payment_id,
            message="Use PayU verify-payment with posted fields",
        )

    async def test_connection(self) -> tuple[bool, str]:
        key, salt = self._key_salt()
        if not key or not salt:
            return False, "PayU key_id and salt_key are required"
        return True, "PayU credentials look valid (format check)"


def hmac_compare(a: str, b: str) -> bool:
    import hmac

    return hmac.compare_digest(a.lower(), b.lower())
