from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

LibraryRequestStatus = Literal[
    "pending_approval",
    "approved",
    "ready_for_pickup",
    "rejected",
    "cancelled",
]
LibraryRequestType = Literal["book", "renewal"]
LibraryFilter = Literal["available", "issued_out", "new_arrivals", "ebooks", "most_popular"]
LibraryAvailabilityStatus = Literal["available", "issued_out"]


class LibrarySummaryOut(BaseModel):
    available_books: int
    my_current_issues: int
    pending_requests: int
    favorite_books: int


class LibraryCategoryOut(BaseModel):
    label: str
    count: int


class LibraryBookSummaryOut(BaseModel):
    id: str
    title: str
    author: str = ""
    subject: str = ""
    category: str = ""
    isbn: str = ""
    publisher: str = ""
    edition: str = ""
    language: str = ""
    shelf_number: str = ""
    cover_image_url: Optional[str] = None
    total_copies: int = 0
    available_copies: int = 0
    availability_status: LibraryAvailabilityStatus = "available"
    estimated_availability_date: Optional[date] = None
    is_favorite: bool = False
    is_digital: bool = False
    popularity_score: int = 0
    created_at: Optional[datetime] = None


class LibraryBookDetailOut(LibraryBookSummaryOut):
    description: str = ""
    digital_resource_url: Optional[str] = None
    digital_resource_format: str = ""


class LibraryIssueOut(BaseModel):
    id: str
    book_id: str
    title: str
    author: str = ""
    subject: str = ""
    cover_image_url: Optional[str] = None
    issue_date: date
    return_due_date: date
    return_date: Optional[date] = None
    days_remaining: int
    renewal_status: Literal["not_requested", "pending_approval", "approved", "ready_for_pickup", "rejected"] = (
        "not_requested"
    )
    renewed_count: int = 0
    is_overdue: bool = False


class LibraryHistoryItemOut(BaseModel):
    id: str
    book_id: str
    title: str
    author: str = ""
    subject: str = ""
    issue_date: date
    return_date: Optional[date] = None
    total_days_borrowed: int = 0


class LibraryRequestOut(BaseModel):
    id: str
    book_id: str
    issue_id: Optional[str] = None
    book_name: str
    request_type: LibraryRequestType = "book"
    request_date: datetime
    status: LibraryRequestStatus = "pending_approval"
    note: str = ""


class LibraryBookRequestIn(BaseModel):
    note: str = Field(default="", max_length=500)


class LibraryRenewalRequestIn(BaseModel):
    note: str = Field(default="", max_length=500)


class LibrarySchoolStatsOut(BaseModel):
    total_books: int
    total_requests: int
    current_issued: int


class LibraryDueRecordIn(BaseModel):
    user_id: str
    record_type: Literal["fine", "deposit"]
    amount: float
    note: str = ""
    recorded_at: date


class LibraryDueRecordOut(BaseModel):
    id: str
    user_id: str
    record_type: Literal["fine", "deposit"]
    amount: float
    note: str
    recorded_at: date
    created_at: datetime
    created_by: str


class LibraryDuesOut(BaseModel):
    total_due: float
    records: List[LibraryDueRecordOut]
