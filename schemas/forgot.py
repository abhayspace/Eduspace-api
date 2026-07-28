"""Schemas for forgot-password flows (student, staff, school login)."""
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class StudentForgotSendIn(BaseModel):
    admission_no: str = Field(min_length=1)
    school_id: str = Field(min_length=1)


class StudentForgotSendOut(BaseModel):
    message: str
    masked_email: str


class StudentForgotVerifyIn(BaseModel):
    admission_no: str = Field(min_length=1)
    school_id: str = Field(min_length=1)
    otp: str = Field(min_length=4, max_length=8)


class StudentForgotResetIn(BaseModel):
    admission_no: str = Field(min_length=1)
    school_id: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class StaffForgotSendIn(BaseModel):
    user_id: str = Field(min_length=1)
    school_id: str = Field(min_length=1)


class StaffForgotVerifyIn(BaseModel):
    user_id: str = Field(min_length=1)
    school_id: str = Field(min_length=1)
    otp: str = Field(min_length=4, max_length=8)


class StaffForgotResetIn(BaseModel):
    user_id: str = Field(min_length=1)
    school_id: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class SchoolForgotSendIn(BaseModel):
    account_type: Literal["office_staff", "school_admin"]
    school_id: str = Field(min_length=1)


class SchoolForgotVerifyIn(BaseModel):
    account_type: Literal["office_staff", "school_admin"]
    school_id: str = Field(min_length=1)
    otp: str = Field(min_length=4, max_length=8)


class SchoolForgotResetIn(BaseModel):
    account_type: Literal["office_staff", "school_admin"]
    school_id: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class LinkEmailIn(BaseModel):
    email: EmailStr
