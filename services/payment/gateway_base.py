"""Common payment gateway interface."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class GatewayCredentials:
    gateway_name: str
    merchant_name: Optional[str] = None
    merchant_id: Optional[str] = None
    key_id: Optional[str] = None
    key_secret: Optional[str] = None
    salt_key: Optional[str] = None
    salt_index: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    webhook_secret: Optional[str] = None
    environment: str = "Sandbox"
    currency: str = "INR"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_sandbox(self) -> bool:
        return (self.environment or "Sandbox").lower() != "production"


@dataclass
class CreateOrderRequest:
    amount: float
    currency: str
    receipt: str
    student_email: Optional[str] = None
    student_name: Optional[str] = None
    notes: dict[str, Any] = field(default_factory=dict)
    callback_url: Optional[str] = None


@dataclass
class CreateOrderResult:
    order_id: str
    amount: float
    currency: str
    gateway_name: str
    checkout_payload: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifyPaymentRequest:
    order_id: str
    payment_id: Optional[str] = None
    signature: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VerifyPaymentResult:
    success: bool
    order_id: str
    payment_id: Optional[str] = None
    method: Optional[str] = None
    amount: Optional[float] = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WebhookResult:
    success: bool
    order_id: Optional[str] = None
    payment_id: Optional[str] = None
    status: str = "pending"
    amount: Optional[float] = None
    method: Optional[str] = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RefundResult:
    success: bool
    refund_id: Optional[str] = None
    message: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentGateway(ABC):
    name: str = "base"

    def __init__(self, credentials: GatewayCredentials):
        self.credentials = credentials

    @abstractmethod
    async def create_order(self, request: CreateOrderRequest) -> CreateOrderResult:
        raise NotImplementedError

    @abstractmethod
    async def verify_payment(self, request: VerifyPaymentRequest) -> VerifyPaymentResult:
        raise NotImplementedError

    @abstractmethod
    async def verify_webhook(
        self, headers: dict[str, str], body: bytes, payload: dict[str, Any]
    ) -> WebhookResult:
        raise NotImplementedError

    @abstractmethod
    async def refund_payment(
        self, payment_id: str, amount: Optional[float] = None
    ) -> RefundResult:
        raise NotImplementedError

    @abstractmethod
    async def get_payment_status(self, payment_id: str) -> VerifyPaymentResult:
        raise NotImplementedError

    async def fetch_order_payment(self, order_id: str) -> VerifyPaymentResult:
        """Optional server-side order poll. Override per gateway when supported."""
        return VerifyPaymentResult(
            success=False,
            order_id=order_id,
            message="Order status refresh not supported for this gateway",
        )

    @abstractmethod
    async def test_connection(self) -> tuple[bool, str]:
        raise NotImplementedError
