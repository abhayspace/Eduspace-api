"""Form service: teacher/admin upsert/publish, student list/fill/submit responses."""
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.form import (
    FormDetailOut,
    FormListItemOut,
    FormResponseOut,
    FormResponseSubmitIn,
    FormUpsertIn,
)

FORMS = "forms"
RESPONSES = "form_responses"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _list_item(row: dict, has_responded: bool = False, submitted_at=None) -> FormListItemOut:
    return FormListItemOut(
        id=row["id"],
        title=row.get("title") or "",
        status=row.get("status") or "draft",
        publishedAt=row.get("published_at"),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
        hasResponded=has_responded,
        submittedAt=submitted_at,
    )


def _detail(row: dict) -> FormDetailOut:
    return FormDetailOut(
        id=row["id"],
        title=row.get("title") or "",
        description=row.get("description") or "",
        settings=row.get("settings") or {},
        questions=row.get("questions") or [],
        status=row.get("status") or "draft",
        publishedAt=row.get("published_at"),
        createdAt=row.get("created_at"),
        updatedAt=row.get("updated_at"),
    )


async def upsert_form(school_id: str, user_id: str, body: FormUpsertIn) -> FormDetailOut:
    """Insert or update a form document (called by teachers/admins on save/publish)."""
    client = get_client()
    now = _now_iso()
    payload = {
        "id": body.id,
        "school_id": school_id,
        "created_by_user_id": user_id,
        "title": body.title,
        "description": body.description,
        "settings": body.settings,
        "questions": body.questions,
        "status": body.status,
        "published_at": body.publishedAt,
        "updated_at": now,
    }
    existing = (
        await client.table(FORMS)
        .select("id,created_by_user_id")
        .eq("school_id", school_id)
        .eq("id", body.id)
        .limit(1)
        .execute()
    )
    if existing.data:
        owner = existing.data[0].get("created_by_user_id")
        if owner and str(owner) != str(user_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only edit your own forms")
        res = await client.table(FORMS).update(payload).eq("id", body.id).execute()
    else:
        payload["created_at"] = body.createdAt or now
        res = await client.table(FORMS).insert(payload).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to save form")
    return _detail(res.data[0])


async def delete_form(school_id: str, user_id: str, form_id: str) -> None:
    client = get_client()
    res = (
        await client.table(FORMS)
        .select("created_by_user_id")
        .eq("school_id", school_id)
        .eq("id", form_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    owner = res.data[0].get("created_by_user_id")
    if owner and str(owner) != str(user_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can only delete your own forms")
    await client.table(FORMS).delete().eq("id", form_id).execute()


async def list_forms_teacher(school_id: str, user_id: str) -> List[FormListItemOut]:
    """List forms created by this teacher/admin."""
    client = get_client()
    res = (
        await client.table(FORMS)
        .select("*")
        .eq("school_id", school_id)
        .eq("created_by_user_id", user_id)
        .order("updated_at", desc=True)
        .limit(500)
        .execute()
    )
    return [_list_item(row) for row in (res.data or [])]


async def list_forms_student(school_id: str, user_id: str) -> List[FormListItemOut]:
    """List published forms for students."""
    client = get_client()
    res = (
        await client.table(FORMS)
        .select("*")
        .eq("school_id", school_id)
        .eq("status", "published")
        .order("updated_at", desc=True)
        .limit(500)
        .execute()
    )
    rows = res.data or []
    if rows:
        form_ids = [r["id"] for r in rows]
        resp_res = (
            await client.table(RESPONSES)
            .select("form_id,submitted_at")
            .eq("school_id", school_id)
            .eq("student_user_id", user_id)
            .in_("form_id", form_ids)
            .execute()
        )
        responded = {r["form_id"]: r.get("submitted_at") for r in (resp_res.data or [])}
    else:
        responded = {}
    return [
        _list_item(row, has_responded=row["id"] in responded, submitted_at=responded.get(row["id"]))
        for row in rows
    ]


async def get_form(school_id: str, form_id: str) -> FormDetailOut:
    client = get_client()
    res = (
        await client.table(FORMS)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", form_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    return _detail(res.data[0])


async def get_form_student(school_id: str, form_id: str) -> FormDetailOut:
    """Get a published form for a student."""
    client = get_client()
    res = (
        await client.table(FORMS)
        .select("*")
        .eq("school_id", school_id)
        .eq("id", form_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    row = res.data[0]
    if row.get("status") != "published":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    return _detail(row)


async def submit_response(
    school_id: str,
    user_id: str,
    user_name: str,
    form_id: str,
    body: FormResponseSubmitIn,
) -> FormResponseOut:
    client = get_client()
    # Verify form exists and is published
    form_res = (
        await client.table(FORMS)
        .select("id")
        .eq("school_id", school_id)
        .eq("id", form_id)
        .eq("status", "published")
        .limit(1)
        .execute()
    )
    if not form_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")

    # Check for existing response (unique constraint)
    existing = (
        await client.table(RESPONSES)
        .select("id")
        .eq("school_id", school_id)
        .eq("form_id", form_id)
        .eq("student_user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_409_CONFLICT, "You have already submitted this form")

    payload = {
        "school_id": school_id,
        "form_id": form_id,
        "student_user_id": user_id,
        "student_name": user_name,
        "answers": [a.model_dump() if hasattr(a, "model_dump") else dict(a) for a in body.answers],
    }
    res = await client.table(RESPONSES).insert(payload).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to submit response")
    row = res.data[0]
    return FormResponseOut(
        id=row["id"],
        formId=row["form_id"],
        studentName=row.get("student_name") or "",
        answers=row.get("answers") or [],
        submittedAt=row.get("submitted_at"),
    )


async def list_responses(school_id: str, form_id: str) -> List[FormResponseOut]:
    client = get_client()
    res = (
        await client.table(RESPONSES)
        .select("*")
        .eq("school_id", school_id)
        .eq("form_id", form_id)
        .order("submitted_at", desc=True)
        .execute()
    )
    return [
        FormResponseOut(
            id=row["id"],
            formId=row["form_id"],
            studentName=row.get("student_name") or "",
            answers=row.get("answers") or [],
            submittedAt=row.get("submitted_at"),
        )
        for row in (res.data or [])
    ]
