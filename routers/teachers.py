"""Teacher directory and CRUD (scoped per school)."""
from typing import List

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse

from database import get_client
from schemas.people import (
    ResetPasswordOut,
    StudentDocumentOut,
    TeacherCreateIn,
    TeacherCreateOut,
    TeacherMedicalIn,
    TeacherMedicalOut,
    TeacherMedicalVisitOut,
    TeacherOut,
    TeacherUpdateIn,
)
from services import student_service
from services import teacher_service
from services.teacher_document_service import (
    delete_teacher_document,
    resolve_teacher_document,
    save_teacher_document,
)
from utils.codes import generate_temp_password
from utils.deps import current_user, require_roles
from utils.security import hash_password

router = APIRouter(prefix="/teachers", tags=["teachers"])


@router.get("/me", response_model=TeacherOut)
async def get_my_teacher_profile(user: dict = Depends(require_roles("teacher"))) -> TeacherOut:
    return await teacher_service.get_teacher_by_user_id(user["school_id"], user["id"])


@router.put("/me", response_model=TeacherOut)
async def update_my_teacher_profile(
    body: TeacherUpdateIn,
    user: dict = Depends(require_roles("teacher")),
) -> TeacherOut:
    return await teacher_service.update_teacher_self(user["school_id"], user["id"], body)


@router.get("/me/medical", response_model=TeacherMedicalOut)
async def get_my_medical_record(
    user: dict = Depends(require_roles("teacher")),
) -> TeacherMedicalOut:
    return await teacher_service.get_my_medical(user["school_id"], user["id"])


@router.put("/me/medical", response_model=TeacherMedicalOut)
async def update_my_medical_record(
    body: TeacherMedicalIn,
    user: dict = Depends(require_roles("teacher")),
) -> TeacherMedicalOut:
    return await teacher_service.update_my_medical(user["school_id"], user["id"], body)


@router.get("/me/medical/visits", response_model=List[TeacherMedicalVisitOut])
async def list_my_medical_visits(
    user: dict = Depends(require_roles("teacher")),
) -> List[TeacherMedicalVisitOut]:
    return await teacher_service.list_my_medical_visits(user["school_id"], user["id"])


@router.post("/upload-document", response_model=StudentDocumentOut)
async def upload_teacher_document(
    file: UploadFile = File(...),
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> StudentDocumentOut:
    saved = await save_teacher_document(user["school_id"], file)
    return StudentDocumentOut(**saved)


@router.delete("/documents/{filename}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher_document_file(
    filename: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> Response:
    delete_teacher_document(user["school_id"], filename)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/documents/{filename}")
async def get_teacher_document(
    filename: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> FileResponse:
    path, mime = resolve_teacher_document(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)


@router.get("", response_model=List[TeacherOut])
async def list_teachers(
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal", "office_staff", "super_admin", "teacher", "student")),
) -> List[TeacherOut]:
    rows = await teacher_service.list_teachers(user["school_id"])
    # Students may only see teachers assigned to their class/section.
    if user.get("role") == "student":
        members = await student_service.get_my_class_group_members(user["school_id"], user["id"])
        allowed = set(members.get("member_user_ids") or [])
        rows = [
            r.model_copy(update={"login_password": None})
            for r in rows
            if r.user_id in allowed
        ]
    return rows


@router.get("/by-user/{user_id}", response_model=TeacherOut)
async def get_teacher_by_user(
    user_id: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> TeacherOut:
    """Look up a teacher by their user_id (used by calendar birthday navigation)."""
    return await teacher_service.get_teacher_by_user_id(user["school_id"], user_id)


@router.get("/{teacher_id}", response_model=TeacherOut)
async def get_teacher(
    teacher_id: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal", "teacher")),
) -> TeacherOut:
    return await teacher_service.get_teacher(user["school_id"], teacher_id)


@router.post("", response_model=TeacherCreateOut, status_code=status.HTTP_201_CREATED)
async def create_teacher(
    body: TeacherCreateIn,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> TeacherCreateOut:
    return await teacher_service.create_teacher(user["school_id"], body)


@router.put("/{teacher_id}", response_model=TeacherOut)
async def update_teacher(
    teacher_id: str,
    body: TeacherUpdateIn,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> TeacherOut:
    return await teacher_service.update_teacher(user["school_id"], teacher_id, body)


@router.delete("/{teacher_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_teacher(
    teacher_id: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> Response:
    await teacher_service.delete_teacher(user["school_id"], teacher_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{teacher_id}/reset-password", response_model=ResetPasswordOut)
async def reset_teacher_password(
    teacher_id: str,
    user: dict = Depends(require_roles("school_admin", "principal", "vice_principal")),
) -> ResetPasswordOut:
    client = get_client()
    profile = (
        await client.table("teachers")
        .select("user_id")
        .eq("school_id", user["school_id"])
        .eq("id", teacher_id)
        .limit(1)
        .execute()
    )
    if not profile.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Teacher not found")
    user_id = profile.data[0]["user_id"]
    u = (
        await client.table("users")
        .select("user_code")
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
    return ResetPasswordOut(user_code=u.data[0]["user_code"] if u.data else "", password=temp)
