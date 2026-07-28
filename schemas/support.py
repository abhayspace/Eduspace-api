"""Support / help request schemas."""
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

SupportIssue = Literal["sign_in", "forgot_password", "other", "registration"]

ISSUE_LABELS = {
    "sign_in": "Sign in issue",
    "forgot_password": "Forgot password issue",
    "other": "Other issue",
    "registration": "Registration issue",
}


class SupportRequestIn(BaseModel):
    issue: SupportIssue
    email: EmailStr
    title: str | None = Field(default=None, min_length=3, max_length=120)
    message: str = Field(min_length=10, max_length=2000)
    school_name: str | None = Field(default=None, alias="schoolName")
    institution_code: str | None = Field(default=None, alias="institutionCode")

    model_config = {"populate_by_name": True}


class SupportRequestOut(BaseModel):
    success: bool = True
    message: str = "Your query has been sent. We will reply to your email shortly."
