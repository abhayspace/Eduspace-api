"""People management schemas — teachers, students, staff."""
from datetime import date, datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class CredentialsOut(BaseModel):
    user_code: str
    password: str


StudentCategory = Literal["General", "OBC", "SC", "ST", "Minor"]
STUDENT_CATEGORIES: tuple[str, ...] = ("General", "OBC", "SC", "ST", "Minor")


class ClassTeacherIn(BaseModel):
    is_class_teacher: bool = False
    class_teacher_class_id: Optional[str] = None
    class_teacher_section_id: Optional[str] = None


class StudentDocumentItem(BaseModel):
    document_url: str
    document_name: str


class TeacherCreateIn(BaseModel):
    full_name: str = Field(min_length=1)
    gender: Optional[str] = None
    dob: Optional[date] = None
    email: EmailStr
    mobile: Optional[str] = None
    address: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    joining_date: Optional[date] = None
    department: Optional[str] = None
    photo_url: Optional[str] = None
    subjects: List[str] = Field(default_factory=list)
    classes_teaching: List[str] = Field(default_factory=list)
    documents: List[StudentDocumentItem] = Field(default_factory=list)
    is_class_teacher: bool = False
    class_teacher_class_id: Optional[str] = None
    class_teacher_section_id: Optional[str] = None

    @model_validator(mode="after")
    def validate_teacher_requirements(self) -> "TeacherCreateIn":
        if not self.subjects:
            raise ValueError("At least one subject is required")
        if not self.classes_teaching:
            raise ValueError("At least one class teaching assignment is required")
        return self


class TeacherUpdateIn(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    email: Optional[EmailStr] = None
    mobile: Optional[str] = None
    address: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    joining_date: Optional[date] = None
    department: Optional[str] = None
    photo_url: Optional[str] = None
    subjects: Optional[List[str]] = None
    classes_teaching: Optional[List[str]] = None
    documents: Optional[List[StudentDocumentItem]] = None
    is_class_teacher: Optional[bool] = None
    class_teacher_class_id: Optional[str] = None
    class_teacher_section_id: Optional[str] = None


class TeacherOut(BaseModel):
    id: str
    user_id: str
    full_name: str
    email: str
    mobile: Optional[str] = None
    user_code: Optional[str] = None
    employee_no: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    address: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    joining_date: Optional[date] = None
    department: Optional[str] = None
    photo_url: Optional[str] = None
    subjects: List[str] = Field(default_factory=list)
    classes_teaching: List[str] = Field(default_factory=list)
    documents: List[StudentDocumentItem] = Field(default_factory=list)
    document_url: Optional[str] = None
    document_name: Optional[str] = None
    is_class_teacher: bool = False
    class_teacher_class_id: Optional[str] = None
    class_teacher_section_id: Optional[str] = None
    class_teacher_class_name: Optional[str] = None
    class_teacher_section_name: Optional[str] = None
    is_active: bool = True
    login_password: Optional[str] = None


class TeacherCreateOut(BaseModel):
    teacher: TeacherOut
    credentials: CredentialsOut


class TeacherMedicalIn(BaseModel):
    """Medical details a teacher maintains for themselves."""

    height: Optional[str] = None
    weight: Optional[str] = None
    blood_group: Optional[str] = None
    allergies: Optional[str] = None
    conditions: Optional[str] = None
    medications: Optional[str] = None
    emergency_name: Optional[str] = None
    emergency_relation: Optional[str] = None
    emergency_mobile: Optional[str] = None
    notes: Optional[str] = None


class TeacherMedicalOut(TeacherMedicalIn):
    teacher_id: str
    full_name: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    updated_at: Optional[datetime] = None


class TeacherMedicalVisitIn(BaseModel):
    """A visit to the school medical room, logged by the teacher."""

    visit_date: date
    visit_time: str = ""
    issue: str = ""
    treatment: str = ""
    prescription: str = ""
    attended_by: str = ""


class TeacherMedicalVisitOut(TeacherMedicalVisitIn):
    id: str
    created_at: Optional[datetime] = None


class StudentCreateIn(BaseModel):
    admission_no: Optional[str] = None
    full_name: str = Field(min_length=1)
    gender: Optional[str] = None
    dob: Optional[date] = None
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    guardian_mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    transport: Optional[str] = None
    class_id: str = Field(min_length=1)
    section_id: str = Field(min_length=1)
    roll_no: Optional[str] = None
    admission_date: Optional[date] = None
    photo_url: Optional[str] = None
    pen_number: Optional[str] = None
    aadhar_number: Optional[str] = None
    category: StudentCategory
    documents: List[StudentDocumentItem] = Field(default_factory=list)

    @field_validator("pen_number")
    @classmethod
    def validate_pen(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 11:
            raise ValueError("PEN must be exactly 11 digits")
        return digits

    @field_validator("aadhar_number")
    @classmethod
    def validate_aadhar(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 12:
            raise ValueError("Aadhaar number must be exactly 12 digits")
        return digits

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        cleaned = str(value).strip()
        if cleaned not in STUDENT_CATEGORIES:
            raise ValueError("Category must be General, OBC, SC, ST, or Minor")
        return cleaned

    @field_validator("guardian_mobile", "alternate_mobile")
    @classmethod
    def validate_mobile(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 10:
            raise ValueError("Mobile number must be exactly 10 digits")
        return digits


class StudentUpdateIn(BaseModel):
    full_name: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    guardian_mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    email: Optional[EmailStr] = None
    address: Optional[str] = None
    transport: Optional[str] = None
    class_id: Optional[str] = None
    section_id: Optional[str] = None
    roll_no: Optional[str] = None
    admission_date: Optional[date] = None
    photo_url: Optional[str] = None
    pen_number: Optional[str] = None
    aadhar_number: Optional[str] = None
    category: Optional[StudentCategory] = None
    documents: Optional[List[StudentDocumentItem]] = None

    @field_validator("pen_number")
    @classmethod
    def validate_pen_update(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 11:
            raise ValueError("PEN must be exactly 11 digits")
        return digits

    @field_validator("aadhar_number")
    @classmethod
    def validate_aadhar_update(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 12:
            raise ValueError("Aadhaar number must be exactly 12 digits")
        return digits

    @field_validator("category")
    @classmethod
    def validate_category_update(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        cleaned = str(value).strip()
        if cleaned not in STUDENT_CATEGORIES:
            raise ValueError("Category must be General, OBC, SC, ST, or Minor")
        return cleaned

    @field_validator("guardian_mobile", "alternate_mobile")
    @classmethod
    def validate_mobile_update(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        digits = "".join(ch for ch in str(value).strip() if ch.isdigit())
        if len(digits) != 10:
            raise ValueError("Mobile number must be exactly 10 digits")
        return digits


class StudentOut(BaseModel):
    id: str
    user_id: str
    full_name: str
    email: Optional[str] = None
    admission_no: Optional[str] = None
    user_code: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    father_name: Optional[str] = None
    mother_name: Optional[str] = None
    guardian_mobile: Optional[str] = None
    alternate_mobile: Optional[str] = None
    address: Optional[str] = None
    transport: Optional[str] = None
    class_id: Optional[str] = None
    section_id: Optional[str] = None
    class_name: Optional[str] = None
    section_name: Optional[str] = None
    roll_no: Optional[str] = None
    admission_date: Optional[date] = None
    photo_url: Optional[str] = None
    is_active: bool = True
    login_password: Optional[str] = None
    pen_number: Optional[str] = None
    aadhar_number: Optional[str] = None
    category: Optional[str] = None
    documents: List[StudentDocumentItem] = Field(default_factory=list)
    document_url: Optional[str] = None
    document_name: Optional[str] = None
    approval_status: str = "approved"


class StudentCreateOut(BaseModel):
    student: StudentOut
    credentials: CredentialsOut
    pending_approval: bool = False


class StaffCreateIn(BaseModel):
    role: str
    full_name: str = Field(min_length=1)
    gender: Optional[str] = None
    dob: Optional[date] = None
    email: EmailStr
    mobile: Optional[str] = None
    address: Optional[str] = None
    qualification: Optional[str] = None
    experience_years: Optional[int] = None
    joining_date: Optional[date] = None
    department: Optional[str] = None
    photo_url: Optional[str] = None


class StaffCreateOut(BaseModel):
    user_id: str
    full_name: str
    role: str
    email: str
    user_code: str
    employee_no: str
    credentials: CredentialsOut


class StaffOut(BaseModel):
    id: str
    full_name: str
    role: str
    email: str
    user_code: Optional[str] = None
    mobile: Optional[str] = None
    employee_no: Optional[str] = None
    department: Optional[str] = None
    qualification: Optional[str] = None
    joining_date: Optional[date] = None


class AdminRoleCreateIn(BaseModel):
    full_name: str = Field(min_length=1)
    email: EmailStr
    mobile: Optional[str] = None
    gender: Optional[str] = None
    dob: Optional[date] = None
    address: Optional[str] = None
    photo_url: Optional[str] = None


class AdminRoleOut(BaseModel):
    id: str
    full_name: str
    email: str
    role: str
    user_code: Optional[str] = None
    mobile: Optional[str] = None
    exists: bool = False


class ResetPasswordOut(BaseModel):
    user_code: str
    password: str
    message: str = "Temporary password generated. Share securely with the user."


class StudentDocumentOut(BaseModel):
    document_url: str
    document_name: str
    content_type: str


class ClassSectionOut(BaseModel):
    id: str
    name: str


class ClassOut(BaseModel):
    id: str
    name: str
    grade_level: Optional[str] = None
    sections: List[ClassSectionOut] = []


class ClassCreateIn(BaseModel):
    name: str
    sections: List[str] = []


class ClassTeacherAssignIn(BaseModel):
    teacher_id: str
    class_id: str
    section_id: str


class SectionUpdateIn(BaseModel):
    name: str


class TeacherBriefOut(BaseModel):
    id: str
    full_name: str
    is_class_teacher: bool = False
    class_teacher_class_id: Optional[str] = None
    class_teacher_section_id: Optional[str] = None


class SectionOut(BaseModel):
    id: str
    class_id: str
    name: str


class SubjectOut(BaseModel):
    id: str
    name: str
    code: Optional[str] = None


class SubjectCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
