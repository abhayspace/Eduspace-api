from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class NoteIn(BaseModel):
    title: str = Field(default="", max_length=200)
    body: str = Field(default="", max_length=20000)
    color: str = Field(default="default", max_length=20)
    is_pinned: bool = False


class NoteUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    body: Optional[str] = Field(default=None, max_length=20000)
    color: Optional[str] = Field(default=None, max_length=20)
    is_pinned: Optional[bool] = None


class NoteOut(BaseModel):
    id: str
    title: str = ""
    body: str = ""
    color: str = "default"
    is_pinned: bool = False
    created_at: datetime
    updated_at: datetime
