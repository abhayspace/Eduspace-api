"""School Feed — posts, media, likes, comments."""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class FeedMediaOut(BaseModel):
    id: str
    file_url: str
    file_name: str
    content_type: str


class FeedCommentOut(BaseModel):
    id: str
    post_id: str
    user_id: str
    author_name: str
    text: str
    created_at: Optional[datetime] = None


class FeedCommentCreateIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class FeedCommentUpdateIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class FeedPostCreateIn(BaseModel):
    caption: str = Field(default="", max_length=2000)
    media_urls: List[str] = Field(default_factory=list, max_length=10)


class FeedPostUpdateIn(BaseModel):
    caption: str = Field(default="", max_length=2000)


class FeedRestrictionIn(BaseModel):
    reason: str = Field(default="", max_length=500)


class FeedRestrictionOut(BaseModel):
    user_id: str
    restricted_by: Optional[str] = None
    reason: str = ""
    created_at: Optional[datetime] = None


class FeedPostOut(BaseModel):
    id: str
    school_id: str
    author_id: str
    author_name: str
    author_role: str
    author_gender: Optional[str] = None
    author_user_code: Optional[str] = None
    author_restricted: bool = False
    caption: str
    created_at: Optional[datetime] = None
    media: List[FeedMediaOut] = Field(default_factory=list)
    like_count: int = 0
    comment_count: int = 0
    liked_by_me: bool = False


class FeedLikeOut(BaseModel):
    liked: bool
    like_count: int
