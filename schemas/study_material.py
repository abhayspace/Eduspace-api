"""Study material folder and file schemas."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Folder
# ---------------------------------------------------------------------------
class StudyFolderOut(BaseModel):
    id: str
    school_id: str
    subject_id: Optional[str] = None
    subject_name: str = ""
    name: str
    created_by: Optional[str] = None
    created_by_name: str = ""
    file_count: int = 0
    latest_file_name: Optional[str] = None
    latest_file_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StudyFolderCreateIn(BaseModel):
    subject_id: Optional[str] = None
    subject_name: str = ""
    name: str = Field(min_length=1, max_length=120)


# ---------------------------------------------------------------------------
# File
# ---------------------------------------------------------------------------
class StudyFileOut(BaseModel):
    id: str
    school_id: str
    folder_id: str
    file_name: str
    file_url: str
    content_type: str = "application/octet-stream"
    file_size: int = 0
    uploaded_by: Optional[str] = None
    uploaded_by_name: str = ""
    created_at: Optional[datetime] = None


class StudyFileUploadOut(BaseModel):
    file_url: str
    file_name: str
    content_type: str
    file_size: int
