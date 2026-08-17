"""Class syllabus schemas — syllabus per class-section, terms, and chapters."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class SyllabusChapterIn(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""


class SyllabusChapterStatusIn(BaseModel):
    completed: bool


class SyllabusChapterOut(BaseModel):
    id: str
    term_id: str
    title: str
    description: str = ""
    sort_order: int = 0
    completed: bool = False
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class SyllabusTermIn(BaseModel):
    name: str = Field(min_length=1)


class SyllabusTermOut(BaseModel):
    id: str
    syllabus_id: str
    name: str
    sort_order: int = 0
    chapters: List[SyllabusChapterOut] = Field(default_factory=list)


class SyllabusCreateIn(BaseModel):
    class_id: str
    section_id: str


class SyllabusOut(BaseModel):
    id: str
    class_id: str
    section_id: str
    class_name: str = ""
    section_name: str = ""
    terms: List[SyllabusTermOut] = Field(default_factory=list)
    created_at: Optional[datetime] = None
