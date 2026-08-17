"""Appointment request schemas — submitted by students, reviewed by the school."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

RequestedWith = Literal["principal", "vice_principal"]
AppointmentStatus = Literal["pending", "approved", "rejected", "cancelled"]


class AppointmentIn(BaseModel):
    title: str = Field(min_length=1)
    requested_with: RequestedWith = "principal"
    appointment_date: date
    appointment_time: str = ""
    description: str = ""


class AppointmentOut(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_role: str
    title: str
    requested_with: RequestedWith
    appointment_date: date
    appointment_time: str = ""
    description: str = ""
    status: AppointmentStatus
    reviewed_by_user_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class AppointmentDecisionIn(BaseModel):
    status: Literal["approved", "rejected"]


class AppointmentCancelIn(BaseModel):
    reason: str = ""
