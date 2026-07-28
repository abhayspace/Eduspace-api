"""Cashfree payment gateway adapter."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from typing import Any, Optional

import httpx

from services.payment.gateway_base import (
    CreateOrderRequest,
    CreateOrderResult,
    PaymentGateway,
    RefundResult,
    VerifyPaymentRequest,
    VerifyPaymentResult,
    WebhookResult,
)


class CashfreeGateway(PaymentGateway):
    name = "cashfree"

    def _host(self) -> str:
        if self.credentials.is_sandbox:
            return "https://sandbox.cashfree.com/pg"
        return "https://api.cashfree.com/pg"

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-client-id": self.credentials.client_id or self.credentials.key_id or "",
            "x-client-secret": self.credentials.client_secret
            or self.credentials.key_secret
            or "",
            "x-api-version": "2023-08-01",
        }

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResult:
        client_id = self.credentials.client_id or self.credentials.key_id
        client_secret = self.credentials.client_secret or self.credentials.key_secret
        if not client_id or not client_secret:
            raise ValueError("Cashfree client_id and client_secret are required")

        order_id = f"CF_{uuid.uuid4().hex[:24]}"
        payload = {
            "order_id": order_id,
            "order_amount": float(request.amount),
            "order_currency": request.currency or self.credentials.currency or "INR",
            "customer_details": {
                "customer_id": (request.student_email or "student")[:50],
                "customer_email": request.student_email or "student@eduspace.local",
                "customer_phone": "9999999999",
            },
            "order_meta": {"notify_url": request.callback_url} if request.callback_url else {},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self._host()}/orders", json=payload, headers=self._headers()
            )
        data = {}
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text}
        if res.status_code >= 400:
            raise ValueError(f"Cashfree order failed: {data}")

        return CreateOrderResult(
            order_id=order_id,
            amount=request.amount,
            currency=payload["order_currency"],
            gateway_name=self.name,
            checkout_payload={
                "payment_session_id": data.get("payment_session_id"),
                "order_id": order_id,
                "environment": "sandbox" if self.credentials.is_sandbox else "production",
            },
            raw=data,
        )

    async def verify_payment(self, request: VerifyPaymentRequest) -> VerifyPaymentResult:
        return await self.get_payment_status(request.order_id)

    async def verify_webhook(
        self, headers: dict[str, str], body: bytes, payload: dict[str, Any]
    ) -> WebhookResult:
        secret = self.credentials.webhook_secret or self.credentials.client_secret or ""
        signature = headers.get("x-webhook-signature") or headers.get("X-Webhook-Signature") or ""
        timestamp = headers.get("x-webhook-timestamp") or headers.get("X-Webhook-Timestamp") or ""
        if secret and signature and timestamp:
            signed = f"{timestamp}{body.decode('utf-8')}".encode("utf-8")
            expected = base64_hmac(secret, signed)
            if not hmac.compare_digest(expected, signature):
                return WebhookResult(success=False, message="Invalid Cashfree webhook signature")

        data = payload.get("data") or payload
        order = data.get("order") or {}
        payment = data.get("payment") or {}
        status_raw = (payment.get("payment_status") or order.get("order_status") or "").upper()
        status = "paid" if status_raw in ("SUCCESS", "PAID") else "pending"
        if status_raw in ("FAILED", "EXPIRED", "CANCELLED"):
            status = "failed"
        if "REFUND" in status_raw:
            status = "refunded"
        return WebhookResult(
            success=True,
            order_id=order.get("order_id"),
            payment_id=payment.get("cf_payment_id") or payment.get("payment_id"),
            status=status,
            amount=order.get("order_amount"),
            method=payment.get("payment_group"),
            message=status_raw or "ok",
            raw=payload,
        )

    async def refund_payment(
        self, payment_id: str, amount: Optional[float] = None
    ) -> RefundResult:
        return RefundResult(success=False, message="Cashfree refund not configured")

    async def get_payment_status(self, payment_id: str) -> VerifyPaymentResult:
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{self._host()}/orders/{payment_id}",
                headers=self._headers(),
            )
        try:
            data = res.json()
        except Exception:
            return VerifyPaymentResult(
                success=False, order_id=payment_id, message=res.text
            )
        status_raw = (data.get("order_status") or "").upper()
        ok = status_raw in ("PAID", "SUCCESS")
        return VerifyPaymentResult(
            success=ok,
            order_id=data.get("order_id") or payment_id,
            payment_id=None,
            amount=data.get("order_amount"),
            message=status_raw,
            raw=data,
        )

    async def test_connection(self) -> tuple[bool, str]:
        client_id = self.credentials.client_id or self.credentials.key_id
        client_secret = self.credentials.client_secret or self.credentials.key_secret
        if not client_id or not client_secret:
            return False, "Cashfree client_id and client_secret are required"
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(f"{self._host()}/orders", headers=self._headers())
        if res.status_code in (200, 404):
            return True, "Cashfree credentials are valid"
        if res.status_code in (401, 403):
            return False, "Invalid Cashfree credentials"
        return False, f"Cashfree test failed ({res.status_code})"


def base64_hmac(secret: str, message: bytes) -> str:
    import base64

    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")
