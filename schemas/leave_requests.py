"""Leave request schemas — submitted by teacher/staff/student, reviewed by the school."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

LeaveType = Literal["single", "multiple"]
LeaveStatus = Literal["pending", "approved", "rejected", "cancelled"]


class LeaveRequestIn(BaseModel):
    title: str = Field(min_length=1)
    leave_type: LeaveType = "single"
    start_date: date
    end_date: date
    description: str = ""


class LeaveRequestOut(BaseModel):
    id: str
    user_id: str
    user_name: str
    user_role: str
    title: str
    leave_type: LeaveType
    start_date: date
    end_date: date
    description: str = ""
    status: LeaveStatus
    reviewed_by_user_id: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    reviewer_user_id: Optional[str] = None
    reviewer_role: str = "admin"


class LeaveRequestDecisionIn(BaseModel):
    status: Literal["approved", "rejected"]


class LeaveRequestCancelIn(BaseModel):
    reason: str = ""
