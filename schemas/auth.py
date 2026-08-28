"""Auth-related request/response schemas."""
from typing import List, Optional

from pydantic import BaseModel, EmailStr, Field


class UserPublic(BaseModel):
    id: str
    # email is a plain str (not EmailStr) because students created without a
    # real email get a placeholder like "student_0001_xxx@eduspace.local",
    # which EmailStr rejects (.local is not a valid TLD).  Email validation
    # belongs on input schemas (RegisterIn, LoginIn, LinkEmailIn), not on
    # this response model that returns data already stored in the DB.
    # Optional because some legacy/migrated student rows may have NULL email.
    email: Optional[str] = None
    full_name: str
    role: str
    school_id: Optional[str] = None
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
    # Trial school flags
    is_trial: bool = False
    trial_expired: bool = False
    trial_status: Optional[str] = None


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


# ── Developer login (EDUERP institution code) ────────────────────────────────

class DeveloperLoginIn(BaseModel):
    password: str = Field(min_length=1)


class DeveloperForgotVerifyIn(BaseModel):
    otp: str = Field(min_length=1)


class DeveloperForgotResetIn(BaseModel):
    otp: str = Field(min_length=1)
    new_password: str = Field(min_length=6)
