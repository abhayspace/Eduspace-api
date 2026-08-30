"""Form routes: teacher/admin upsert/delete, student list/get/submit responses."""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Response, status

from schemas.form import (
    FormDetailOut,
    FormListItemOut,
    FormResponseOut,
    FormResponseSubmitIn,
    FormUpsertIn,
)
from services import form_service
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/forms", tags=["forms"])

staff_only = require_roles("teacher", "school_admin", "principal", "vice_principal")


@router.get("", response_model=List[FormListItemOut])
async def list_forms(user: dict = Depends(current_user)) -> List[FormListItemOut]:
    if user["role"] == "student":
        return await form_service.list_forms_student(user["school_id"], user["id"])
    return await form_service.list_forms_teacher(user["school_id"], user["id"])


@router.get("/{form_id}", response_model=FormDetailOut)
async def get_form(form_id: str, user: dict = Depends(current_user)) -> FormDetailOut:
    if user["role"] == "student":
        return await form_service.get_form_student(user["school_id"], form_id)
    return await form_service.get_form(user["school_id"], form_id)


@router.put("", response_model=FormDetailOut)
async def upsert_form(
    body: FormUpsertIn,
    user: dict = Depends(staff_only),
) -> FormDetailOut:
    return await form_service.upsert_form(user["school_id"], user["id"], body)


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_form(
    form_id: str,
    user: dict = Depends(staff_only),
) -> Response:
    await form_service.delete_form(user["school_id"], user["id"], form_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{form_id}/responses", response_model=FormResponseOut, status_code=status.HTTP_201_CREATED)
async def submit_response(
    form_id: str,
    body: FormResponseSubmitIn,
    user: dict = Depends(current_user),
) -> FormResponseOut:
    if user["role"] != "student":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students can submit form responses")
    return await form_service.submit_response(
        user["school_id"],
        user["id"],
        user.get("full_name") or "Student",
        form_id,
        body,
    )


@router.get("/{form_id}/responses", response_model=List[FormResponseOut])
async def list_responses(
    form_id: str,
    user: dict = Depends(staff_only),
) -> List[FormResponseOut]:
    return await form_service.list_responses(user["school_id"], form_id)
