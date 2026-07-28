"""Auth-related request/response schemas."""
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserPublic(BaseModel):
    id: str
    email: EmailStr
    full_name: str
    role: str
    school_id: str
    admission_no: Optional[str] = None
    user_code: Optional[str] = None
    is_active: bool = True
    gender: Optional[str] = None
    teacher_id: Optional[str] = None
    is_class_teacher: bool = False
    class_teacher_class_id: Optional[str] = None
    class_teacher_section_id: Optional[str] = None
    class_teacher_class_name: Optional[str] = None
    class_teacher_section_name: Optional[str] = None
    # School Management: SCH + legacy ADM share one inbox across devices.
    message_actor_ids: Optional[List[str]] = None


class LoginIn(BaseModel):
    # New flow: identifier + role + school_id. Legacy flow: email + password.
    email: Optional[EmailStr] = None
    identifier: Optional[str] = None
    password: str = Field(min_length=1)
    school_id: Optional[str] = None
    role: Optional[str] = None


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=6)
    full_name: str = Field(min_length=1)
    role: str = "student"
    school_id: str


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=6)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserPublic
