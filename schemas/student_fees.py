"""Schemas for the comprehensive student fees overview page."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


def _uuid() -> str:
    import uuid

    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Fee component (derived from fees table with computed status)
# ---------------------------------------------------------------------------

FeeComponentStatus = Literal["paid", "partially_paid", "pending", "overdue"]


class FeeComponentOut(BaseModel):
    id: str = Field(default_factory=_uuid)
    title: str
    amount: float  # current remaining amount
    original_amount: float  # original total before partial payments
    amount_paid: float  # how much has been paid so far
    due_date: Optional[str] = None
    status: FeeComponentStatus = "pending"
    paid_at: Optional[str] = None
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Payment history item (from fee_payments + receipts)
# ---------------------------------------------------------------------------


class FeePaymentHistoryOut(BaseModel):
    id: str
    invoice_number: Optional[str] = None
    amount: float
    total: float
    currency: str = "INR"
    gateway_name: Optional[str] = None
    payment_method: Optional[str] = None
    payment_status: str = "paid"
    payment_date: Optional[str] = None
    receipt_number: Optional[str] = None
    receipt_url: Optional[str] = None
    receipt_id: Optional[str] = None
    transaction_reference: Optional[str] = None
    fee_title: Optional[str] = None


# ---------------------------------------------------------------------------
# Discount / scholarship / concession
# ---------------------------------------------------------------------------

DiscountType = Literal["discount", "scholarship", "concession"]


class FeeDiscountOut(BaseModel):
    id: str
    discount_type: DiscountType
    name: str
    description: Optional[str] = None
    original_amount: float
    discount_amount: float
    final_amount: float
    reason: Optional[str] = None
    is_active: bool = True
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    created_at: Optional[str] = None


class FeeDiscountIn(BaseModel):
    student_id: Optional[str] = None
    student_email: Optional[str] = None
    discount_type: DiscountType = "concession"
    name: str
    description: str = ""
    original_amount: float = Field(..., ge=0)
    discount_amount: float = Field(..., ge=0)
    final_amount: float = Field(..., ge=0)
    reason: str = ""
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


# ---------------------------------------------------------------------------
# Fee notice
# ---------------------------------------------------------------------------

NoticeType = Literal["reminder", "due_date_extension", "new_charge", "general"]
NoticePriority = Literal["low", "normal", "high", "urgent"]


class FeeNoticeOut(BaseModel):
    id: str
    title: str
    body: Optional[str] = None
    notice_type: NoticeType = "reminder"
    priority: NoticePriority = "normal"
    is_pinned: bool = False
    published_at: str
    expires_at: Optional[str] = None


class FeeNoticeIn(BaseModel):
    title: str
    body: str = ""
    notice_type: NoticeType = "reminder"
    priority: NoticePriority = "normal"
    target_class_id: Optional[str] = None
    target_section_id: Optional[str] = None
    is_pinned: bool = False
    expires_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Overview response — the main payload for the student fees page
# ---------------------------------------------------------------------------


class FeeOverviewOut(BaseModel):
    # Overview totals
    total_fees: float = 0.0  # total for current academic session
    total_paid: float = 0.0
    remaining_balance: float = 0.0
    overdue_amount: float = 0.0
    upcoming_amount: float = 0.0
    next_payment_due_date: Optional[str] = None
    academic_session: str = ""

    # Fee components
    components: List[FeeComponentOut] = []

    # Payment history
    payments: List[FeePaymentHistoryOut] = []

    # Upcoming & overdue
    upcoming: List[FeeComponentOut] = []
    overdue: List[FeeComponentOut] = []

    # Discounts
    discounts: List[FeeDiscountOut] = []

    # Notices
    notices: List[FeeNoticeOut] = []

    # Gateway enabled?
    online_payment_enabled: bool = False
