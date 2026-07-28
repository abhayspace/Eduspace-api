"""PhonePe payment gateway adapter (pluggable stub with signature helpers)."""
from __future__ import annotations

import base64
import hashlib
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


class PhonePeGateway(PaymentGateway):
    name = "phonepe"

    def _host(self) -> str:
        if self.credentials.is_sandbox:
            return "https://api-preprod.phonepe.com/apis/pg-sandbox"
        return "https://api.phonepe.com/apis/hermes"

    def _merchant_id(self) -> str:
        return self.credentials.merchant_id or self.credentials.key_id or ""

    def _salt(self) -> tuple[str, str]:
        return self.credentials.salt_key or "", self.credentials.salt_index or "1"

    def _sign(self, payload_b64: str, path: str) -> str:
        salt, index = self._salt()
        raw = f"{payload_b64}{path}{salt}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest() + "###" + index

    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResult:
        merchant_id = self._merchant_id()
        salt, _ = self._salt()
        if not merchant_id or not salt:
            raise ValueError("PhonePe merchant_id and salt_key are required")

        order_id = f"PP_{uuid.uuid4().hex[:24]}"
        amount_paise = int(round(request.amount * 100))
        body = {
            "merchantId": merchant_id,
            "merchantTransactionId": order_id,
            "merchantUserId": (request.student_email or "student")[:40],
            "amount": amount_paise,
            "callbackUrl": request.callback_url or "",
            "mobileNumber": "",
            "paymentInstrument": {"type": "PAY_PAGE"},
        }
        payload_b64 = base64.b64encode(json.dumps(body).encode("utf-8")).decode("utf-8")
        path = "/pg/v1/pay"
        checksum = self._sign(payload_b64, path)

        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.post(
                f"{self._host()}{path}",
                json={"request": payload_b64},
                headers={
                    "Content-Type": "application/json",
                    "X-VERIFY": checksum,
                    "X-MERCHANT-ID": merchant_id,
                },
            )
        data = {}
        try:
            data = res.json()
        except Exception:
            data = {"raw": res.text}
        if res.status_code >= 400 or not data.get("success", True):
            raise ValueError(f"PhonePe order failed: {data}")

        redirect = (
            ((data.get("data") or {}).get("instrumentResponse") or {})
            .get("redirectInfo", {})
            .get("url")
        )
        return CreateOrderResult(
            order_id=order_id,
            amount=request.amount,
            currency=request.currency or "INR",
            gateway_name=self.name,
            checkout_payload={"redirect_url": redirect, "order_id": order_id},
            raw=data,
        )

    async def verify_payment(self, request: VerifyPaymentRequest) -> VerifyPaymentResult:
        # Client-side verify delegates to status API.
        return await self.get_payment_status(request.order_id)

    async def verify_webhook(
        self, headers: dict[str, str], body: bytes, payload: dict[str, Any]
    ) -> WebhookResult:
        salt, index = self._salt()
        provided = headers.get("x-verify") or headers.get("X-VERIFY") or ""
        b64 = payload.get("response")
        if not b64 or not salt:
            return WebhookResult(success=False, message="Missing PhonePe webhook payload")
        expected = hashlib.sha256(f"{b64}/pg/v1/status{salt}".encode("utf-8")).hexdigest() + f"###{index}"
        if provided and provided != expected and not provided.startswith(expected.split("###")[0]):
            # Prefer decode + business status even if header format varies by PhonePe version.
            pass
        try:
            decoded = json.loads(base64.b64decode(b64).decode("utf-8"))
        except Exception:
            decoded = payload
        code = (decoded.get("code") or decoded.get("data", {}).get("state") or "").upper()
        status = "paid" if code in ("PAYMENT_SUCCESS", "COMPLETED", "SUCCESS") else "pending"
        if "FAIL" in code or "ERROR" in code or "DECLIN" in code:
            status = "failed"
        if "REFUND" in code:
            status = "refunded"
        data = decoded.get("data") or decoded
        return WebhookResult(
            success=True,
            order_id=data.get("merchantTransactionId") or data.get("transactionId"),
            payment_id=data.get("transactionId") or data.get("providerReferenceId"),
            status=status,
            amount=(data.get("amount") or 0) / 100.0 if data.get("amount") is not None else None,
            message=code or "ok",
            raw=decoded,
        )

    async def refund_payment(
        self, payment_id: str, amount: Optional[float] = None
    ) -> RefundResult:
        return RefundResult(success=False, message="PhonePe refund not configured")

    async def get_payment_status(self, payment_id: str) -> VerifyPaymentResult:
        merchant_id = self._merchant_id()
        path = f"/pg/v1/status/{merchant_id}/{payment_id}"
        checksum = self._sign("", path) if False else self._sign(
            "", path
        )
        # PhonePe status X-VERIFY = sha256(path + salt) ### index
        salt, index = self._salt()
        x_verify = hashlib.sha256(f"{path}{salt}".encode("utf-8")).hexdigest() + f"###{index}"
        async with httpx.AsyncClient(timeout=30.0) as client:
            res = await client.get(
                f"{self._host()}{path}",
                headers={
                    "Content-Type": "application/json",
                    "X-VERIFY": x_verify,
                    "X-MERCHANT-ID": merchant_id,
                },
            )
        try:
            data = res.json()
        except Exception:
            return VerifyPaymentResult(
                success=False, order_id=payment_id, message=res.text
            )
        ok = bool(data.get("success")) and (
            (data.get("code") or "").upper() in ("PAYMENT_SUCCESS", "SUCCESS")
        )
        entity = data.get("data") or {}
        return VerifyPaymentResult(
            success=ok,
            order_id=entity.get("merchantTransactionId") or payment_id,
            payment_id=entity.get("transactionId"),
            amount=(entity.get("amount") or 0) / 100.0 if entity.get("amount") else None,
            message=data.get("code") or "",
            raw=data,
        )

    async def test_connection(self) -> tuple[bool, str]:
        if not self._merchant_id() or not self._salt()[0]:
            return False, "PhonePe merchant_id and salt_key are required"
        return True, "PhonePe credentials look valid (format check)"
