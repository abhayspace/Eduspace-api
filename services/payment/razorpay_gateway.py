"""Razorpay payment gateway adapter."""
from __future__ import annotations

import hashlib
import hmac
import json
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


class RazorpayGateway(PaymentGateway):
    name = "razorpay"

    def _auth(self) -> tuple[str, str]:
        key_id = self.credentials.key_id or ""
        key_secret = self.credentials.key_secret or ""
        return key_id, key_secret

    def _base_url(self) -> str:
        return "https://api.razorpay.com/v1"

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResult:
        key_id, key_secret = self._auth()
        if not key_id or not key_secret:
            raise ValueError("Razorpay key_id and key_secret are required")

        amount_paise = int(round(request.amount * 100))
        payload = {
            "amount": amount_paise,
            "currency": request.currency or self.credentials.currency or "INR",
            "receipt": request.receipt[:40],
            "notes": request.notes or {},
        }

        if self.credentials.is_sandbox and key_id.startswith("rzp_test") is False:
            # Still call API; sandbox is determined by key type.
            pass

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self._base_url()}/orders",
                json=payload,
                auth=(key_id, key_secret),
            )
        if res.status_code >= 400:
            detail = res.text
            try:
                detail = res.json().get("error", {}).get("description") or detail
            except Exception:
                pass
            raise ValueError(f"Razorpay order failed: {detail}")

        data = res.json()
        order_id = data["id"]
        checkout: dict[str, Any] = {
            "key": key_id,
            "order_id": order_id,
            "amount": amount_paise,
            "currency": payload["currency"],
            "name": self.credentials.merchant_name or "School Fees",
            "prefill": {"email": request.student_email},
            "notes": request.notes,
        }

        # Payment link gives Expo / mobile a URL to open (no native SDK required).
        try:
            link_payload = {
                "amount": amount_paise,
                "currency": payload["currency"],
                "accept_partial": False,
                "reference_id": request.receipt[:40],
                "description": self.credentials.merchant_name or "School Fees",
                "notes": {**(request.notes or {}), "razorpay_order_id": order_id},
                "notify": {"sms": False, "email": False},
            }
            if request.callback_url:
                link_payload["callback_url"] = request.callback_url
                link_payload["callback_method"] = "get"
            async with httpx.AsyncClient(timeout=30.0) as client:
                link_res = await client.post(
                    f"{self._base_url()}/payment_links",
                    json=link_payload,
                    auth=(key_id, key_secret),
                )
            if link_res.status_code < 400:
                link_data = link_res.json()
                checkout["redirect_url"] = link_data.get("short_url")
                checkout["payment_link_id"] = link_data.get("id")
                data["payment_link"] = link_data
        except Exception:
            pass

        return CreateOrderResult(
            order_id=order_id,
            amount=request.amount,
            currency=payload["currency"],
            gateway_name=self.name,
            checkout_payload=checkout,
            raw=data,
        )

    async def verify_payment(self, request: VerifyPaymentRequest) -> VerifyPaymentResult:
        _, key_secret = self._auth()
        payment_id = request.payment_id or ""
        signature = request.signature or ""
        if not request.order_id or not payment_id or not signature or not key_secret:
            return VerifyPaymentResult(
                success=False,
                order_id=request.order_id,
                payment_id=payment_id,
                message="Missing order_id, payment_id, or signature",
            )
        body = f"{request.order_id}|{payment_id}".encode("utf-8")
        expected = hmac.new(key_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        ok = hmac.compare_digest(expected, signature)
        return VerifyPaymentResult(
            success=ok,
            order_id=request.order_id,
            payment_id=payment_id,
            message="Signature verified" if ok else "Invalid signature",
            raw={"expected": expected},
        )

    async def verify_webhook(
        self, headers: dict[str, str], body: bytes, payload: dict[str, Any]
    ) -> WebhookResult:
        secret = self.credentials.webhook_secret or self.credentials.key_secret or ""
        signature = headers.get("x-razorpay-signature") or headers.get("X-Razorpay-Signature") or ""
        if not secret or not signature:
            return WebhookResult(success=False, message="Missing webhook signature/secret")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return WebhookResult(success=False, message="Invalid webhook signature")

        event = payload.get("event") or ""
        entity = ((payload.get("payload") or {}).get("payment") or {}).get("entity") or {}
        refund_entity = ((payload.get("payload") or {}).get("refund") or {}).get("entity") or {}
        status = "pending"
        if event in ("payment.captured", "order.paid"):
            status = "paid"
        elif event in ("payment.failed",):
            status = "failed"
        elif event in ("payment.refunded", "refund.processed", "refund.created"):
            status = "refunded"
        order_id = entity.get("order_id") or refund_entity.get("payment_id") and entity.get("order_id")
        # payment.refunded still carries payment entity with order_id
        if not order_id:
            order_id = entity.get("order_id")
        payment_id = entity.get("id") or refund_entity.get("payment_id")
        notes = entity.get("notes") or {}
        if not order_id and isinstance(notes, dict):
            order_id = notes.get("razorpay_order_id")
        return WebhookResult(
            success=True,
            order_id=order_id,
            payment_id=payment_id,
            status=status,
            amount=(entity.get("amount") or 0) / 100.0 if entity.get("amount") is not None else None,
            method=entity.get("method"),
            message=event or "ok",
            raw=payload,
        )

    async def refund_payment(
        self, payment_id: str, amount: Optional[float] = None
    ) -> RefundResult:
        key_id, key_secret = self._auth()
        body: dict[str, Any] = {}
        if amount is not None:
            body["amount"] = int(round(amount * 100))
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self._base_url()}/payments/{payment_id}/refund",
                json=body,
                auth=(key_id, key_secret),
            )
        if res.status_code >= 400:
            return RefundResult(success=False, message=res.text)
        data = res.json()
        return RefundResult(success=True, refund_id=data.get("id"), raw=data)

    async def get_payment_status(self, payment_id: str) -> VerifyPaymentResult:
        key_id, key_secret = self._auth()
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{self._base_url()}/payments/{payment_id}",
                auth=(key_id, key_secret),
            )
        if res.status_code >= 400:
            return VerifyPaymentResult(
                success=False, order_id="", payment_id=payment_id, message=res.text
            )
        data = res.json()
        ok = data.get("status") in ("captured", "authorized")
        return VerifyPaymentResult(
            success=ok,
            order_id=data.get("order_id") or "",
            payment_id=payment_id,
            method=data.get("method"),
            amount=(data.get("amount") or 0) / 100.0,
            message=data.get("status") or "",
            raw=data,
        )

    async def fetch_order_payment(self, order_id: str) -> VerifyPaymentResult:
        """Server-side check: fetch payments for an order from Razorpay."""
        key_id, key_secret = self._auth()
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{self._base_url()}/orders/{order_id}/payments",
                auth=(key_id, key_secret),
            )
        if res.status_code >= 400:
            return VerifyPaymentResult(
                success=False, order_id=order_id, message=res.text
            )
        data = res.json()
        items = data.get("items") or []
        for item in items:
            if item.get("status") in ("captured", "authorized"):
                return VerifyPaymentResult(
                    success=True,
                    order_id=order_id,
                    payment_id=item.get("id"),
                    method=item.get("method"),
                    amount=(item.get("amount") or 0) / 100.0,
                    message=item.get("status") or "captured",
                    raw=item,
                )
        return VerifyPaymentResult(
            success=False,
            order_id=order_id,
            message="No captured payment for order yet",
            raw=data,
        )

    async def test_connection(self) -> tuple[bool, str]:
        key_id, key_secret = self._auth()
        if not key_id or not key_secret:
            return False, "Razorpay key_id and key_secret are required"
        # Lightweight authenticated call
        async with httpx.AsyncClient(timeout=20.0) as client:
            res = await client.get(
                f"{self._base_url()}/orders",
                params={"count": 1},
                auth=(key_id, key_secret),
            )
        if res.status_code in (200, 201):
            return True, "Razorpay credentials are valid"
        if res.status_code in (401, 403):
            return False, "Invalid Razorpay credentials"
        return False, f"Razorpay test failed ({res.status_code})"
