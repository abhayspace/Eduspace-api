"""Form schemas — teacher/admin-created forms and student responses."""
from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, Field


class FormUpsertIn(BaseModel):
    """Full form document uploaded by the teacher/admin on publish/save."""
    id: str
    title: str = ""
    description: str = ""
    settings: dict = Field(default_factory=dict)
    questions: List[dict] = Field(default_factory=list)
    status: str = "draft"
    publishedAt: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class FormListItemOut(BaseModel):
    id: str
    title: str = ""
    status: str = "draft"
    publishedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None
    hasResponded: bool = False
    submittedAt: Optional[datetime] = None


class FormDetailOut(BaseModel):
    id: str
    title: str = ""
    description: str = ""
    settings: dict = Field(default_factory=dict)
    questions: List[dict] = Field(default_factory=list)
    status: str = "draft"
    publishedAt: Optional[datetime] = None
    createdAt: Optional[datetime] = None
    updatedAt: Optional[datetime] = None


class FormAnswerIn(BaseModel):
    questionId: str
    value: Any = None


class FormResponseSubmitIn(BaseModel):
    answers: List[FormAnswerIn] = Field(default_factory=list)


class FormResponseOut(BaseModel):
    id: str
    formId: str
    studentName: str = ""
    answers: List[dict] = Field(default_factory=list)
    submittedAt: Optional[datetime] = None
