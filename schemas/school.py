"""School registration / lookup schemas."""
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class School(BaseModel):
    id: str
    name: str
    short_name: str = ""
    logo_color: str = "#2563EB"
    institution_code: str = ""


class SchoolSearchResult(School):
    city: Optional[str] = None
    address: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None


class SchoolSearchIn(BaseModel):
    """Two-step school lookup: location first, then admission + contact."""

    school_name: Optional[str] = Field(default=None, alias="schoolName")
    city: Optional[str] = None
    state: Optional[str] = None
    admission_no: Optional[str] = Field(default=None, alias="admissionNo")
    contact: Optional[str] = None

    model_config = {"populate_by_name": True}


class VerifyCodeIn(BaseModel):
    code: str = Field(min_length=1)


class AdmissionLookupIn(BaseModel):
    """Public student admission lookup within a school."""

    institution_code: str = Field(min_length=1, alias="institutionCode")
    student_name: Optional[str] = Field(default=None, alias="studentName")
    father_name: Optional[str] = Field(default=None, alias="fatherName")
    mother_name: Optional[str] = Field(default=None, alias="motherName")
    contact: Optional[str] = None

    model_config = {"populate_by_name": True}


class AdmissionLookupResult(BaseModel):
    full_name: str = Field(alias="fullName")
    father_name: Optional[str] = Field(default=None, alias="fatherName")
    mother_name: Optional[str] = Field(default=None, alias="motherName")
    admission_no: str = Field(alias="admissionNo")

    model_config = {"populate_by_name": True}


class SchoolRegisterIn(BaseModel):
    """Payload for self-service school registration.

    The institution code and temporary password are generated server-side.
    School email and administrator email must both be OTP-verified before registration.
    Creates two accounts: institutional school login (SCH***) and administrator (ADM***).
    """
    # Step 1 — School information
    school_name: str = Field(min_length=2, alias="schoolName")
    address: Optional[str] = Field(default=None, alias="address")
    city: Optional[str] = Field(default=None, alias="city")
    state: Optional[str] = Field(default=None, alias="state")
    pincode: Optional[str] = Field(default=None, alias="pincode")
    school_email: EmailStr = Field(alias="schoolEmail")
    school_phone: Optional[str] = Field(default=None, alias="schoolPhone")

    # Step 2 — Administrator
    admin_full_name: str = Field(min_length=2, alias="adminFullName")
    admin_email: EmailStr = Field(alias="adminEmail")
    admin_mobile: Optional[str] = Field(default=None, alias="adminMobile")

    # Step 3 — Additional info
    education_board: Optional[str] = Field(default=None, alias="educationBoard")
    school_type: Optional[str] = Field(default=None, alias="schoolType")
    level_of_education: Optional[str] = Field(default=None, alias="levelOfEducation")
    total_students: Optional[int] = Field(default=None, alias="totalStudents", ge=1)
    total_teachers: Optional[int] = Field(default=None, alias="totalTeachers", ge=1)
    established_date: Optional[str] = Field(default=None, alias="establishedDate")
    website: Optional[str] = None
    logo_base64: Optional[str] = Field(default=None, alias="logoBase64")
    logo_filename: Optional[str] = Field(default=None, alias="logoFilename")
    logo_content_type: Optional[str] = Field(default=None, alias="logoContentType")

    # Legacy / optional extras
    academic_session: Optional[str] = Field(default=None, alias="academicSession")

    model_config = {"populate_by_name": True}


class SchoolRegisterOut(BaseModel):
    success: bool = True
    message: str
    school_id: Optional[str] = None
    institution_code: Optional[str] = None


class SchoolProfileOut(BaseModel):
    id: Optional[str] = None
    school_name: str = Field(alias="schoolName")
    institution_code: str = Field(alias="institutionCode")
    logo_url: Optional[str] = Field(default=None, alias="logoUrl")
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    school_email: Optional[str] = Field(default=None, alias="schoolEmail")
    school_phone: Optional[str] = Field(default=None, alias="schoolPhone")
    education_board: Optional[str] = Field(default=None, alias="educationBoard")
    established_date: Optional[str] = Field(default=None, alias="establishedDate")
    school_type: Optional[str] = Field(default=None, alias="schoolType")
    level_of_education: Optional[str] = Field(default=None, alias="levelOfEducation")
    total_students: Optional[int] = Field(default=None, alias="totalStudents")
    total_teachers: Optional[int] = Field(default=None, alias="totalTeachers")
    principal_name: Optional[str] = Field(default=None, alias="principalName")
    admin_name: Optional[str] = Field(default=None, alias="adminName")
    website: Optional[str] = None
    gst_number: Optional[str] = Field(default=None, alias="gstNumber")
    subscription_plan: Optional[str] = Field(default=None, alias="subscriptionPlan")
    admin_email: Optional[str] = Field(default=None, alias="adminEmail")
    admin_mobile: Optional[str] = Field(default=None, alias="adminMobile")

    model_config = {"populate_by_name": True}


class SchoolProfileUpdateIn(BaseModel):
    """Editable school profile fields. Email changes require OTP verification."""

    education_board: Optional[str] = Field(default=None, alias="educationBoard")
    established_date: Optional[str] = Field(default=None, alias="establishedDate")
    school_email: Optional[EmailStr] = Field(default=None, alias="schoolEmail")
    school_phone: Optional[str] = Field(default=None, alias="schoolPhone")
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    website: Optional[str] = None

    model_config = {"populate_by_name": True}
