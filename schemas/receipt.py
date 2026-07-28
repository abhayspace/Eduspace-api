"""Fee receipt schemas (list / detail / search)."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class FeeReceiptOut(BaseModel):
    id: str
    receipt_number: str
    school_id: str
    student_id: Optional[str] = None
    payment_id: str
    invoice_number: Optional[str] = None
    pdf_url: Optional[str] = None
    generated_at: Optional[str] = None
    generated_by: Optional[str] = None
    created_at: Optional[str] = None
    # Denormalized helpers for list UIs
    student_name: Optional[str] = None
    admission_no: Optional[str] = None
    class_name: Optional[str] = None
    section_name: Optional[str] = None
    amount_paid: Optional[float] = None
    payment_status: Optional[str] = None
    payment_method: Optional[str] = None
    payment_date: Optional[str] = None
    currency: Optional[str] = None


class FeeReceiptListOut(BaseModel):
    items: list[FeeReceiptOut]
    total: int = 0


class AdminReceiptSearchIn(BaseModel):
    student_name: Optional[str] = Field(default=None, alias="studentName")
    admission_no: Optional[str] = Field(default=None, alias="admissionNo")
    receipt_number: Optional[str] = Field(default=None, alias="receiptNumber")
    class_name: Optional[str] = Field(default=None, alias="className")
    date_from: Optional[str] = Field(default=None, alias="dateFrom")
    date_to: Optional[str] = Field(default=None, alias="dateTo")
    payment_status: Optional[str] = Field(default=None, alias="paymentStatus")
    limit: int = Field(default=50, ge=1, le=200)
    offset: int = Field(default=0, ge=0)

    model_config = {"populate_by_name": True}


class EnsureReceiptIn(BaseModel):
    """Ensure PDF receipt for a recent-fees transaction id (``fpay-*`` or ``pay-*``)."""

    transaction_id: str = Field(..., alias="transactionId", min_length=1)

    model_config = {"populate_by_name": True}


class EnsureReceiptOut(FeeReceiptOut):
    transaction_id: Optional[str] = None


class ReceiptSnapshot(BaseModel):
    """Serialized payload used to (re)generate the PDF."""

    school: dict[str, Any]
    student: dict[str, Any]
    receipt: dict[str, Any]
    payment: dict[str, Any]
    fee_lines: list[dict[str, Any]] = Field(default_factory=list)
    totals: dict[str, Any] = Field(default_factory=dict)
