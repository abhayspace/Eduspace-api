"""School live activity feed schemas."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ActivityType = Literal[
    "attendance_marked",
    "fee_paid",
    "fee_due_added",
    "announcement_created",
    "student_added",
    "teacher_added",
    "staff_added",
    "school_timing_updated",
    "period_timing_updated",
]


class SchoolActivityOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: ActivityType
    title: str
    subtitle: str
    occurred_at: datetime = Field(
        validation_alias="occurred_at",
        serialization_alias="occurredAt",
    )
