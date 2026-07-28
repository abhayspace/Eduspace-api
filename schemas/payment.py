"""Payment gateway + fee payment schemas."""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


GatewayName = Literal["razorpay", "phonepe", "cashfree", "payu", "other"]
EnvironmentName = Literal["Sandbox", "Production", "Other"]


class PaymentGatewayUpsertIn(BaseModel):
    gateway_name: GatewayName
    merchant_name: Optional[str] = None
    merchant_id: Optional[str] = None
    key_id: Optional[str] = None
    key_secret: Optional[str] = None
    salt_key: Optional[str] = None
    salt_index: Optional[str] = None
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    webhook_secret: Optional[str] = None
    environment: EnvironmentName = "Sandbox"
    currency: str = "INR"


class CreateFeeOrderIn(BaseModel):
    fee_ids: List[str] = Field(default_factory=list)
    amount: Optional[float] = None


class VerifyFeePaymentIn(BaseModel):
    gateway: Optional[str] = None
    gateway_order_id: str = Field(..., alias="order_id")
    gateway_payment_id: Optional[str] = Field(default=None, alias="payment_id")
    signature: Optional[str] = None
    raw: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}
