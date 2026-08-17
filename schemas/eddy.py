"""Schemas for Eddy AI Buddy chat."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class EddyChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class EddyChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    history: List[EddyChatMessage] = Field(default_factory=list, max_length=40)
    style: Literal["professional", "friendly", "teacher", "simple"] = "friendly"
    length: Literal["short", "medium", "detailed"] = "medium"
    language: Literal["english", "hindi", "hinglish"] = "english"


class EddyChatOut(BaseModel):
    reply: str
    model: str
