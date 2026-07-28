"""Student directory and CRUD (scoped per school)."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from database import get_client
from schemas.people import (
    ResetPasswordOut,
    StudentCreateIn,
    StudentCreateOut,
    StudentDocumentOut,
    StudentOut,
    StudentUpdateIn,
)
from services import student_service
from services.student_document_service import (
    delete_student_document,
    resolve_student_document,
    save_student_document,
)
from utils.codes import generate_temp_password
from utils.deps import require_roles
from utils.security import hash_password

router = APIRouter(prefix="/students", tags=["students"])


@router.post("/upload-document", response_model=StudentDocumentOut)
async def upload_student_document(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> StudentDocumentOut:
    saved = await save_student_document(user["school_id"], file)
    return StudentDocumentOut(**saved)


@router.delete("/documents/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student_document_file(
    filename: str,
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> Response:
    delete_student_document(user["school_id"], filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{filename}")
async def get_student_document(
    filename: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal", "teacher")),
) -> FileResponse:
    path, mime = resolve_student_document(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)


def _strip_password_for_teacher(student: StudentOut, user: dict) -> StudentOut:
    if user.get("role") == "teacher":
        return student.model_copy(update={"login_password": None})
    return student


@router.get("/me", response_model=StudentOut)
async def get_my_student_profile(
    user: dict = Depends(require_roles("student")),
) -> StudentOut:
    student = await student_service.get_student_by_user_id(user["school_id"], user["id"])
    return student.model_copy(update={"login_password": None})


@router.get("", response_model=List[StudentOut])
async def list_students(
    class_id: Optional[str] = None,
    section_id: Optional[str] = None,
    search: Optional[str] = None,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal", "teacher")),
) -> List[StudentOut]:
    rows = await student_service.list_students(user["school_id"], class_id, section_id, search)
    return [_strip_password_for_teacher(row, user) for row in rows]


@router.get("/{student_id}", response_model=StudentOut)
async def get_student(
    student_id: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal", "teacher")),
) -> StudentOut:
    student = await student_service.get_student(user["school_id"], student_id)
    return _strip_password_for_teacher(student, user)


@router.post("", response_model=StudentCreateOut, status_code=status.HTTP_201_CREATED)
async def create_student(
    body: StudentCreateIn,
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> StudentCreateOut:
    return await student_service.create_student(user["school_id"], body)


@router.put("/{student_id}", response_model=StudentOut)
async def update_student(
    student_id: str,
    body: StudentUpdateIn,
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> StudentOut:
    return await student_service.update_student(user["school_id"], student_id, body)


@router.delete("/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_student(
    student_id: str,
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> Response:
    await student_service.delete_student(user["school_id"], student_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{student_id}/reset-password", response_model=ResetPasswordOut)
async def reset_student_password(
    student_id: str,
    user: dict = Depends(require_roles("school_admin", "principal")),
) -> ResetPasswordOut:
    client = get_client()
    profile = (
        await client.table("students")
        .select("user_id")
        .eq("school_id", user["school_id"])
        .eq("id", student_id)
        .limit(1)
        .execute()
    )
    if not profile.data:
        from fastapi import HTTPException
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Student not found")
    user_id = profile.data[0]["user_id"]
    u = (
        await client.table("users")
        .select("user_code,admission_no")
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    temp = generate_temp_password()
    await client.table("users").update({
        "password_hash": hash_password(temp),
        "login_password": temp,
        "must_change_password": True,
    }).eq("id", user_id).execute()
    code = ""
    if u.data:
        code = u.data[0].get("admission_no") or u.data[0].get("user_code") or ""
    return ResetPasswordOut(user_code=code, password=temp)
