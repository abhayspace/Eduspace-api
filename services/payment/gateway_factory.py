"""Gateway factory — register providers without changing fee module callers."""
from __future__ import annotations

from typing import Dict, Type

from fastapi import HTTPException, status

from services.payment.cashfree_gateway import CashfreeGateway
from services.payment.gateway_base import GatewayCredentials, PaymentGateway
from services.payment.other_gateway import OtherGateway
from services.payment.payu_gateway import PayUGateway
from services.payment.phonepe_gateway import PhonePeGateway
from services.payment.razorpay_gateway import RazorpayGateway

_REGISTRY: Dict[str, Type[PaymentGateway]] = {
    "razorpay": RazorpayGateway,
    "phonepe": PhonePeGateway,
    "cashfree": CashfreeGateway,
    "payu": PayUGateway,
    "other": OtherGateway,
}


def supported_gateways() -> list[str]:
    return sorted(_REGISTRY.keys())


def register_gateway(name: str, cls: Type[PaymentGateway]) -> None:
    _REGISTRY[name.strip().lower()] = cls


def create_gateway(credentials: GatewayCredentials) -> PaymentGateway:
    name = (credentials.gateway_name or "").strip().lower()
    cls = _REGISTRY.get(name)
    if not cls:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Unsupported gateway '{credentials.gateway_name}'. "
            f"Supported: {', '.join(supported_gateways())}",
        )
    return cls(credentials)
