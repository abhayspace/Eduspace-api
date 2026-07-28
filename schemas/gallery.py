"""Gallery folder and media schemas."""
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class GalleryFolderOut(BaseModel):
    id: str
    school_id: str
    name: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    latest_media_type: Optional[Literal["image", "video"]] = None
    latest_file_url: Optional[str] = None


class GalleryFolderCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GalleryFolderUpdateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class GalleryMediaOut(BaseModel):
    id: str
    school_id: str
    folder_id: str
    media_type: Literal["image", "video"]
    file_url: str
    file_name: str
    content_type: str
    created_at: Optional[datetime] = None
