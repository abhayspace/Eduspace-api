"""Schemas for academic / operational content endpoints."""
import uuid
from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AnnouncementRecipientItem(BaseModel):
    user_id: str
    full_name: str
    admission_no: Optional[str] = None


class AnnouncementAudienceTargets(BaseModel):
    """Used when audience == 'class'."""

    class_ids: List[str] = Field(default_factory=list)
    section_ids: List[str] = Field(default_factory=list)
    all_sections: bool = True
    class_names: List[str] = Field(default_factory=list)
    section_names: List[str] = Field(default_factory=list)


class Announcement(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    title: str
    body: str
    audience: str = "all"
    author: str = "EduSpace"
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    recipient_user_id: Optional[str] = None
    recipient_name: Optional[str] = None
    recipient_type: Optional[str] = None
    recipients: List[AnnouncementRecipientItem] = Field(default_factory=list)
    audience_targets: AnnouncementAudienceTargets = Field(
        default_factory=AnnouncementAudienceTargets
    )
    created_at: datetime = Field(default_factory=_now)


class AnnouncementAttachmentOut(BaseModel):
    attachment_url: str
    attachment_name: str


class HomeworkAttachmentOut(BaseModel):
    attachment_url: str
    attachment_name: str


class HomeworkItem(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    subject: str
    title: str
    description: str = ""
    class_name: str
    section_name: str = ""
    due_date: str
    assigned_by: str = ""
    assigned_by_user_id: Optional[str] = None
    attachment_url: Optional[str] = None
    attachment_name: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class TimetableSlot(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    class_name: str
    day: str
    start: str
    end: str
    subject: str
    teacher: str
    room: str = ""


class AttendanceRec(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    student_email: str
    class_name: str
    date: str
    status: str


class StaffAttendanceOut(BaseModel):
    id: str
    user_id: str
    date: str
    status: str


class StaffAttendanceMarkIn(BaseModel):
    user_id: str
    date: str
    status: str


class StaffAttendancePeriodSummary(BaseModel):
    working_days: int
    present_days: int
    absent_days: int
    pct: int


class StaffAttendanceTodaySummary(BaseModel):
    label: str
    is_holiday: bool


class StaffAttendanceDayOut(BaseModel):
    date: str
    status: str
    status_label: str


class StaffAttendanceSummaryOut(BaseModel):
    period: StaffAttendancePeriodSummary
    today: StaffAttendanceTodaySummary
    period_label: str
    days: List[StaffAttendanceDayOut] = Field(default_factory=list)


class ClassStudentAttendanceItem(BaseModel):
    student_id: str
    user_id: str
    full_name: str
    roll_no: Optional[str] = None
    admission_no: Optional[str] = None
    status: Optional[str] = None


class ClassStudentAttendanceOut(BaseModel):
    class_name: str
    section_name: str
    date: str
    students: List[ClassStudentAttendanceItem] = Field(default_factory=list)


class ClassStudentAttendanceMarkIn(BaseModel):
    student_id: str
    date: str
    status: str


class ExpenseTransactionOut(BaseModel):
    id: str
    title: str
    amount: float
    type: str
    transaction_date: str
    created_at: datetime
    source: str = "manual"


class ExpenseTransactionCreateIn(BaseModel):
    title: str
    amount: float
    type: str = "expense"
    transaction_date: Optional[str] = None
    notes: Optional[str] = None


class ExpenseTransactionUpdateIn(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = None
    type: Optional[str] = None
    transaction_date: Optional[str] = None


class SavingOut(BaseModel):
    id: str
    title: str
    amount: float
    saved_date: str
    sort_order: int = 0
    created_at: datetime


class SavingCreateIn(BaseModel):
    title: str
    amount: float
    saved_date: Optional[str] = None


class SavingUpdateIn(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = None
    saved_date: Optional[str] = None
    sort_order: Optional[int] = None


class FeeItem(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    student_email: str
    title: str
    amount: float
    due_date: str
    status: str = "pending"
    paid_at: Optional[str] = None
    created_at: Optional[str] = None


class FeeTransactionOut(BaseModel):
    id: str
    title: str
    amount: float
    student_email: Optional[str] = None
    student_name: Optional[str] = None
    kind: Literal["paid", "due_added"] = "paid"
    status_label: str = "Paid"
    occurred_at: Optional[str] = None
    due_reason: Optional[str] = None
    receipt_id: Optional[str] = None
    receipt_number: Optional[str] = None
    pdf_url: Optional[str] = None
    payment_method: Optional[str] = None
    invoice_number: Optional[str] = None
    gateway_name: Optional[str] = None
    class_name: Optional[str] = None
    section_name: Optional[str] = None
    admission_no: Optional[str] = None
    roll_no: Optional[str] = None


class FeeStructureSectionOut(BaseModel):
    id: str
    name: str
    monthly_amount: Optional[float] = None


class FeeStructureClassOut(BaseModel):
    id: str
    name: str
    monthly_amount: Optional[float] = None
    sections: List[FeeStructureSectionOut] = []


class FeeAmountIn(BaseModel):
    amount: float = Field(..., ge=0)


class StudentFeeDueIn(BaseModel):
    amount: float = Field(..., gt=0)
    title: Optional[str] = None
    due_date: Optional[str] = None


class StudentFeeMarkPaidIn(BaseModel):
    mode: Literal["this_month", "full", "custom"] = "full"
    amount: Optional[float] = Field(default=None, gt=0)


class Examination(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    name: str
    term: Optional[str] = None
    class_name: Optional[str] = None
    subject: Optional[str] = None
    exam_date: Optional[str] = None
    max_marks: float = 100


class ExaminationBatchIn(BaseModel):
    name: str = Field(min_length=1)
    term: Optional[str] = None
    class_names: List[str] = Field(min_length=1)
    subjects: List[str] = Field(min_length=1)
    max_marks: float = 100


class ExaminationBatchOut(BaseModel):
    name: str
    created: int
    examinations: List[Examination] = Field(default_factory=list)


class ExaminationGroupOut(BaseModel):
    name: str
    class_names: List[str] = Field(default_factory=list)
    subjects: List[str] = Field(default_factory=list)
    max_marks: float = 100


class ExaminationGroupReplaceIn(ExaminationBatchIn):
    original_name: str = Field(min_length=1)


class DatesheetEntryIn(BaseModel):
    examination_id: str
    exam_date: str
    max_marks: Optional[float] = None


class DatesheetUpdateIn(BaseModel):
    exam_name: str
    class_name: Optional[str] = None
    entries: List[DatesheetEntryIn] = Field(min_length=1)


class ResultItem(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    examination_id: Optional[str] = None
    student_email: str
    marks_obtained: float = 0
    grade: Optional[str] = None


class ResultBulkItemIn(BaseModel):
    examination_id: str
    student_email: str
    marks_obtained: float
    grade: Optional[str] = None


class ResultBulkIn(BaseModel):
    items: List[ResultBulkItemIn] = Field(min_length=1)


class ResultBulkOut(BaseModel):
    created: int
    results: List[ResultItem] = Field(default_factory=list)


class ChatMessage(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str
    sender_id: str
    sender_name: str
    sender_role: str
    recipient_id: Optional[str] = None
    group_id: Optional[str] = None
    text: str = ""
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    media_name: Optional[str] = None
    reply_to_id: Optional[str] = None
    reply_to_text: Optional[str] = None
    reply_to_sender: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class ChatMediaUploadOut(BaseModel):
    media_url: str
    media_type: str
    media_name: str
    content_type: str


class ChatSendIn(BaseModel):
    text: str = Field(default="", max_length=1000)
    recipient_id: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None
    media_name: Optional[str] = None
    reply_to_id: Optional[str] = None

    @model_validator(mode="after")
    def require_text_or_media(self) -> "ChatSendIn":
        text = (self.text or "").strip()
        media_url = (self.media_url or "").strip() or None
        self.text = text
        self.media_url = media_url
        if not text and not media_url:
            raise ValueError("Message must include text or media")
        if media_url and self.media_type not in ("image", "video", "file"):
            raise ValueError("media_type must be image, video, or file")
        return self


class ChatDeleteIn(BaseModel):
    message_ids: List[str] = Field(min_length=1)
    scope: Literal["me", "everyone"] = "me"


class ChatPeerOut(BaseModel):
    user_id: str
    full_name: str
    role: str
    user_code: str = ""
    gender: Optional[str] = None


class ChatThreadOut(BaseModel):
    peer_id: str
    peer_name: str
    peer_role: str
    peer_user_code: str = ""
    peer_gender: Optional[str] = None
    last_message: str
    last_message_at: datetime
    last_sender_id: str = ""
    unread_count: int = 0



class RegisterPushIn(BaseModel):
    user_id: str
    platform: str
    device_token: str


class NotificationItem(BaseModel):
    id: str = Field(default_factory=_uuid)
    school_id: str = ""
    user_id: Optional[str] = None
    title: str
    body: str = ""
    is_read: bool = False
    created_at: datetime = Field(default_factory=_now)


class SchoolTimingOut(BaseModel):
    start_time: str = ""
    start_meridiem: str = "AM"
    end_time: str = ""
    end_meridiem: str = "PM"
    updated_at: Optional[datetime] = None


class SchoolTimingUpsertIn(BaseModel):
    start_time: str
    start_meridiem: str
    end_time: str
    end_meridiem: str


class PeriodSlotIn(BaseModel):
    start_time: str = ""
    start_meridiem: str = "AM"
    end_time: str = ""
    end_meridiem: str = "AM"


class PeriodTimetableClassIn(BaseModel):
    class_id: str
    class_name: str


class PeriodTimetableCreateIn(BaseModel):
    classes: List[PeriodTimetableClassIn]
    period_count: int = Field(gt=0)


class PeriodTimetableUpdateIn(BaseModel):
    classes: Optional[List[PeriodTimetableClassIn]] = None
    period_count: Optional[int] = Field(default=None, gt=0)
    periods: Optional[List[PeriodSlotIn]] = None
    times_saved: Optional[bool] = None


class PeriodSlotOut(PeriodSlotIn):
    period_index: int


class PeriodTimetableOut(BaseModel):
    id: str
    classes: List[PeriodTimetableClassIn]
    period_count: int
    periods: List[PeriodSlotOut]
    times_saved: bool


class ClassSectionPeriodAssignmentIn(BaseModel):
    period_index: int = Field(ge=0)
    subject_id: Optional[str] = None
    teacher_id: Optional[str] = None


class ClassSectionScheduleUpsertIn(BaseModel):
    class_id: str
    section_id: str
    day_of_week: str
    assignments: List[ClassSectionPeriodAssignmentIn]


class ClassSectionPeriodOut(BaseModel):
    period_index: int
    start_time: str = ""
    start_meridiem: str = "AM"
    end_time: str = ""
    end_meridiem: str = "AM"
    subject_id: Optional[str] = None
    subject_name: str = ""
    teacher_id: Optional[str] = None
    teacher_name: str = ""


class ClassSectionScheduleOut(BaseModel):
    class_id: str
    class_name: str
    section_id: str
    section_name: str
    day_of_week: str
    has_period_timetable: bool
    periods: List[ClassSectionPeriodOut]


class TeacherScheduleSlotOut(BaseModel):
    period_index: int
    start_time: str = ""
    start_meridiem: str = "AM"
    end_time: str = ""
    end_meridiem: str = "AM"
    class_name: str
    section_name: str
    subject_name: str = ""
    is_substitute: bool = False
    day_of_week: Optional[str] = None


class TeacherSubstituteAssignIn(BaseModel):
    teacher_id: str
    class_id: str
    section_id: str
    period_index: int = Field(ge=0)
    day_of_week: str


class TeacherFreePeriodOut(BaseModel):
    period_index: int
    start_time: str = ""
    start_meridiem: str = "AM"
    end_time: str = ""
    end_meridiem: str = "AM"


class TeacherScheduleDayOut(BaseModel):
    day_of_week: str
    class_slots: List[TeacherScheduleSlotOut]
    free_periods: List[TeacherFreePeriodOut]


class TeacherScheduleOut(BaseModel):
    teacher_id: str
    full_name: str
    user_code: str = ""
    subjects: List[str] = Field(default_factory=list)
    has_period_timetable: bool
    days: List[TeacherScheduleDayOut] = Field(default_factory=list)
    class_slots: List[TeacherScheduleSlotOut]
    free_periods: List[TeacherFreePeriodOut]
