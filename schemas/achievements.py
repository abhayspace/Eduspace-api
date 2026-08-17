from datetime import date
from typing import Optional
from pydantic import BaseModel, Field
from enum import Enum


class AchievementType(str, Enum):
    SCHOOL = "school"
    STUDENT = "student"
    TEACHER = "teacher"


class AchievementCategory(str, Enum):
    ACADEMIC = "academic"
    SPORTS = "sports"
    CULTURAL = "cultural"
    COMPETITION = "competition"
    OLYMPIAD = "olympiad"
    EVENT = "event"
    ATTENDANCE = "attendance"
    OTHER = "other"


class AchievementLevel(str, Enum):
    SCHOOL = "school"
    DISTRICT = "district"
    STATE = "state"
    NATIONAL = "national"
    INTERNATIONAL = "international"


class FileType(str, Enum):
    PDF = "pdf"
    IMAGE = "image"


class AchievementImage(BaseModel):
    id: str
    achievement_id: str
    image_url: str
    created_at: str


class AchievementAttachment(BaseModel):
    id: str
    achievement_id: str
    file_url: str
    file_name: Optional[str] = None
    file_type: FileType
    created_at: str


class AchievementAssignment(BaseModel):
    id: str
    achievement_id: str
    user_type: AchievementType
    user_id: str
    created_at: str


class AchievementBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1, max_length=5000)
    type: AchievementType
    category: Optional[AchievementCategory] = None
    level: Optional[AchievementLevel] = None
    achievement_date: Optional[date] = None
    cover_image: Optional[str] = None
    pinned: bool = False


class AchievementCreate(AchievementBase):
    assigned_student_ids: Optional[list[str]] = None
    assigned_teacher_ids: Optional[list[str]] = None
    images: Optional[list[str]] = None
    attachments: Optional[list[dict]] = None  # [{"file_url": "...", "file_name": "...", "file_type": "..."}]


class AchievementUpdate(AchievementBase):
    assigned_student_ids: Optional[list[str]] = None
    assigned_teacher_ids: Optional[list[str]] = None
    images: Optional[list[str]] = None
    attachments: Optional[list[dict]] = None


class AchievementOut(AchievementBase):
    id: str
    school_id: str
    created_by: str
    created_at: str
    updated_at: str
    images: list[AchievementImage] = []
    attachments: list[AchievementAttachment] = []
    assignments: list[AchievementAssignment] = []
    assigned_count: int = 0


class AchievementListOut(BaseModel):
    achievements: list[AchievementOut]
    total: int
    page: int
    page_size: int


class AchievementFilter(BaseModel):
    type: Optional[AchievementType] = None
    category: Optional[AchievementCategory] = None
    level: Optional[AchievementLevel] = None
    year: Optional[int] = None
    month: Optional[int] = None
    search: Optional[str] = None
