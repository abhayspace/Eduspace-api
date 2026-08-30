"""Complaints & Behaviour Management — schemas."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Complaints
# ---------------------------------------------------------------------------

class ComplaintCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    category: str = Field(default="other", max_length=50)
    severity: str = Field(default="low", max_length=20)
    is_anonymous: bool = False
    incident_date: Optional[date] = None
    student_id: Optional[str] = None
    student_name: str = ""
    involved_user_id: Optional[str] = None
    involved_name: str = ""
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None


class ComplaintUpdateIn(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    severity: Optional[str] = None
    status: Optional[str] = None
    assigned_to_user_id: Optional[str] = None
    assigned_to_name: Optional[str] = None
    resolution_notes: Optional[str] = None
    is_anonymous: Optional[bool] = None


class ComplaintActivityOut(BaseModel):
    id: str
    complaint_id: str
    action: str
    description: str
    actor_name: str
    actor_role: str
    is_internal: bool = False
    created_at: Optional[datetime] = None


class ComplaintOut(BaseModel):
    id: str
    school_id: str
    title: str
    description: str
    category: str
    severity: str
    status: str
    is_anonymous: bool = False
    incident_date: Optional[date] = None
    submitted_by_user_id: Optional[str] = None
    submitted_by_name: str
    submitted_by_role: str
    student_id: Optional[str] = None
    student_name: str
    involved_user_id: Optional[str] = None
    involved_name: str
    assigned_to_user_id: Optional[str] = None
    assigned_to_name: str
    resolution_notes: str = ""
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    activity: List[ComplaintActivityOut] = []


class ComplaintStatusUpdateIn(BaseModel):
    status: str = Field(min_length=1, max_length=20)
    resolution_notes: str = Field(default="", max_length=5000)


class ComplaintAssignIn(BaseModel):
    assigned_to_user_id: str
    assigned_to_name: str = ""


class ComplaintNoteIn(BaseModel):
    note: str = Field(min_length=1, max_length=3000)
    is_internal: bool = True


# ---------------------------------------------------------------------------
# Behaviour
# ---------------------------------------------------------------------------

class BehaviourRecordCreateIn(BaseModel):
    student_id: str
    student_name: str = ""
    class_name: str = ""
    section_name: str = ""
    type: str = Field(default="positive", max_length=20)
    category: str = Field(default="other", max_length=50)
    description: str = Field(min_length=1, max_length=3000)
    severity: str = Field(default="low", max_length=20)
    incident_date: Optional[date] = None
    is_visible_to_student: bool = True


class BehaviourRecordUpdateIn(BaseModel):
    type: Optional[str] = None
    category: Optional[str] = None
    description: Optional[str] = None
    severity: Optional[str] = None
    incident_date: Optional[date] = None
    is_visible_to_student: Optional[bool] = None


class BehaviourRecordOut(BaseModel):
    id: str
    school_id: str
    student_id: str
    student_name: str
    class_name: str = ""
    section_name: str = ""
    type: str
    category: str
    description: str
    severity: str = "low"
    incident_date: Optional[date] = None
    recorded_by_user_id: Optional[str] = None
    recorded_by_name: str
    recorded_by_role: str
    is_visible_to_student: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Disciplinary actions
# ---------------------------------------------------------------------------

class DisciplinaryActionCreateIn(BaseModel):
    student_id: str
    student_name: str = ""
    behaviour_record_id: Optional[str] = None
    action_type: str = Field(default="warning", max_length=50)
    notes: str = Field(default="", max_length=3000)
    status: str = Field(default="pending", max_length=20)
    action_date: Optional[date] = None


class DisciplinaryActionOut(BaseModel):
    id: str
    school_id: str
    student_id: str
    student_name: str
    behaviour_record_id: Optional[str] = None
    action_type: str
    notes: str = ""
    status: str
    action_date: Optional[date] = None
    created_by_name: str
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Analytics (admin overview)
# ---------------------------------------------------------------------------

class ComplaintAnalyticsOut(BaseModel):
    total_complaints: int = 0
    pending: int = 0
    under_review: int = 0
    resolved: int = 0
    rejected: int = 0
    high_priority: int = 0
    total_behaviour: int = 0
    positive_behaviour: int = 0
    negative_behaviour: int = 0
    by_category: dict = {}
    by_severity: dict = {}
    by_status: dict = {}
