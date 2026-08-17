"""School medical visit schemas — for the school admin/principal view."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class SchoolMedicalVisitIn(BaseModel):
    """A visit to the school medical room, logged by the school admin."""

    person_name: str = ""
    person_role: str = ""
    visit_date: date
    visit_time: str = ""
    issue: str = ""
    treatment: str = ""
    prescription: str = ""
    attended_by: str = ""


class SchoolMedicalVisitOut(SchoolMedicalVisitIn):
    id: str
    user_id: str
    person_name: str = ""
    person_role: str = ""
    created_at: Optional[datetime] = None
