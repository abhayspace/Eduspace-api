"""School calendar event schemas."""
from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

CalendarEventType = Literal["holiday", "birthday", "special_day"]


class CalendarEventOut(BaseModel):
    id: str
    event_type: CalendarEventType
    title: str
    description: Optional[str] = None
    event_date: date
    end_date: Optional[date] = None
    source: str = "school"
    person_type: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None


class CalendarMonthOut(BaseModel):
    month: int
    year: int
    events: list[CalendarEventOut]


class CalendarEventCreateIn(BaseModel):
    event_type: CalendarEventType
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    event_date: date
    end_date: Optional[date] = None


class CalendarEventUpdateIn(BaseModel):
    event_type: Optional[CalendarEventType] = None
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = Field(default=None, max_length=1000)
    event_date: Optional[date] = None
    end_date: Optional[date] = None


class CalendarSettingsOut(BaseModel):
    open_on_sunday: bool = False


class CalendarSettingsUpdateIn(BaseModel):
    open_on_sunday: bool
