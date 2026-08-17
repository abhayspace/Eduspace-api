"""Pydantic models for student module settings."""
from pydantic import BaseModel


class StudentSettingsOut(BaseModel):
    class_teacher_can_add_student: bool = True
    student_approval_required: bool = True


class StudentSettingsUpdateIn(BaseModel):
    class_teacher_can_add_student: bool
    student_approval_required: bool
