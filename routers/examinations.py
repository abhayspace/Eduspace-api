"""Examinations (scoped per school) — create, datesheet, PDF."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from database import get_client
from schemas.content import (
    DatesheetUpdateIn,
    Examination,
    ExaminationBatchIn,
    ExaminationBatchOut,
    ExaminationGroupOut,
    ExaminationGroupReplaceIn,
)
from services.exam_pdf import generate_datesheet_pdf
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/examinations", tags=["examinations"])

_COLUMNS = "id,school_id,name,term,class_name,subject,exam_date,max_marks"
_SETUP_ROLES = ("school_admin", "principal", "vice_principal", "super_admin")


@router.get("", response_model=List[Examination])
async def list_examinations(
    name: Optional[str] = Query(default=None),
    class_name: Optional[str] = Query(default=None),
    user: dict = Depends(current_user),
) -> List[Examination]:
    client = get_client()
    q = (
        client.table("examinations")
        .select(_COLUMNS)
        .eq("school_id", user["school_id"])
    )
    if name:
        q = q.eq("name", name)
    if class_name:
        q = q.eq("class_name", class_name)
    res = await q.order("exam_date", desc=True).limit(500).execute()
    return [Examination(**row) for row in (res.data or [])]


@router.get("/names", response_model=List[str])
async def list_examination_names(user: dict = Depends(current_user)) -> List[str]:
    client = get_client()
    res = (
        await client.table("examinations")
        .select("name")
        .eq("school_id", user["school_id"])
        .limit(500)
        .execute()
    )
    names = sorted({(row.get("name") or "").strip() for row in (res.data or []) if row.get("name")})
    return names


@router.get("/groups", response_model=List[ExaminationGroupOut])
async def list_examination_groups(user: dict = Depends(current_user)) -> List[ExaminationGroupOut]:
    client = get_client()
    res = (
        await client.table("examinations")
        .select("name,class_name,subject,max_marks")
        .eq("school_id", user["school_id"])
        .limit(1000)
        .execute()
    )
    grouped: dict[str, dict] = {}
    for row in res.data or []:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        bucket = grouped.setdefault(
            name,
            {"classes": set(), "subjects": set(), "max_marks": float(row.get("max_marks") or 100)},
        )
        if row.get("class_name"):
            bucket["classes"].add(str(row["class_name"]).strip())
        if row.get("subject"):
            bucket["subjects"].add(str(row["subject"]).strip())
        if row.get("max_marks") is not None:
            bucket["max_marks"] = float(row["max_marks"])
    return [
        ExaminationGroupOut(
            name=name,
            class_names=sorted(data["classes"]),
            subjects=sorted(data["subjects"]),
            max_marks=data["max_marks"],
        )
        for name, data in sorted(grouped.items(), key=lambda item: item[0].lower())
    ]


@router.post("", response_model=Examination)
async def create_examination(
    body: Examination,
    user: dict = Depends(require_roles(*_SETUP_ROLES)),
) -> Examination:
    client = get_client()
    row = {
        "school_id": user["school_id"],
        "name": body.name,
        "term": body.term,
        "class_name": body.class_name,
        "subject": body.subject,
        "exam_date": body.exam_date,
        "max_marks": body.max_marks,
    }
    inserted = await client.table("examinations").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create examination")
    return Examination(**inserted.data[0])


@router.post("/batch", response_model=ExaminationBatchOut)
async def create_examination_batch(
    body: ExaminationBatchIn,
    user: dict = Depends(require_roles(*_SETUP_ROLES)),
) -> ExaminationBatchOut:
    client = get_client()
    school_id = user["school_id"]
    name = body.name.strip()
    rows = []
    for class_name in body.class_names:
        for subject in body.subjects:
            rows.append(
                {
                    "school_id": school_id,
                    "name": name,
                    "term": body.term,
                    "class_name": class_name.strip(),
                    "subject": subject.strip(),
                    "exam_date": None,
                    "max_marks": body.max_marks,
                }
            )
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No examinations to create")
    inserted = await client.table("examinations").insert(rows).execute()
    created = [Examination(**row) for row in (inserted.data or [])]
    return ExaminationBatchOut(name=name, created=len(created), examinations=created)


@router.put("/group", response_model=ExaminationBatchOut)
async def replace_examination_group(
    body: ExaminationGroupReplaceIn,
    user: dict = Depends(require_roles(*_SETUP_ROLES)),
) -> ExaminationBatchOut:
    client = get_client()
    school_id = user["school_id"]
    original = body.original_name.strip()
    name = body.name.strip()
    existing = (
        await client.table("examinations")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("name", original)
        .limit(1000)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Examination not found")

    date_map = {
        (str(row.get("class_name") or "").strip(), str(row.get("subject") or "").strip()): row.get(
            "exam_date"
        )
        for row in existing.data
    }

    await (
        client.table("examinations")
        .delete()
        .eq("school_id", school_id)
        .eq("name", original)
        .execute()
    )

    rows = []
    for class_name in body.class_names:
        for subject in body.subjects:
            cn = class_name.strip()
            sub = subject.strip()
            rows.append(
                {
                    "school_id": school_id,
                    "name": name,
                    "term": body.term,
                    "class_name": cn,
                    "subject": sub,
                    "exam_date": date_map.get((cn, sub)),
                    "max_marks": body.max_marks,
                }
            )
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No examinations to save")
    inserted = await client.table("examinations").insert(rows).execute()
    created = [Examination(**row) for row in (inserted.data or [])]
    return ExaminationBatchOut(name=name, created=len(created), examinations=created)


@router.delete("/group", status_code=status.HTTP_204_NO_CONTENT)
async def delete_examination_group(
    name: str = Query(...),
    user: dict = Depends(require_roles(*_SETUP_ROLES)),
) -> Response:
    client = get_client()
    existing = (
        await client.table("examinations")
        .select("id")
        .eq("school_id", user["school_id"])
        .eq("name", name.strip())
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Examination not found")
    await (
        client.table("examinations")
        .delete()
        .eq("school_id", user["school_id"])
        .eq("name", name.strip())
        .execute()
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/datesheet", response_model=List[Examination])
async def update_datesheet(
    body: DatesheetUpdateIn,
    user: dict = Depends(require_roles(*_SETUP_ROLES)),
) -> List[Examination]:
    client = get_client()
    school_id = user["school_id"]
    updated: List[Examination] = []
    for entry in body.entries:
        patch = {"exam_date": entry.exam_date}
        if entry.max_marks is not None:
            patch["max_marks"] = entry.max_marks
        res = (
            await client.table("examinations")
            .update(patch)
            .eq("school_id", school_id)
            .eq("id", entry.examination_id)
            .execute()
        )
        if res.data:
            updated.append(Examination(**res.data[0]))
    return updated


@router.get("/datesheet/pdf")
async def download_datesheet_pdf(
    exam_name: str = Query(...),
    class_name: Optional[str] = Query(default=None),
    user: dict = Depends(
        require_roles("school_admin", "principal", "vice_principal", "teacher")
    ),
) -> Response:
    client = get_client()
    school_id = user["school_id"]
    q = (
        client.table("examinations")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("name", exam_name)
    )
    if class_name:
        q = q.eq("class_name", class_name)
    exams = await q.order("exam_date").limit(200).execute()
    rows = exams.data or []
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No datesheet entries found")

    school_res = (
        await client.table("schools")
        .select("school_name,name,city")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    school = (school_res.data or [{}])[0]

    pdf = generate_datesheet_pdf(
        {
            "school": school,
            "exam_name": exam_name,
            "class_name": class_name or "",
            "rows": [
                {
                    "subject": r.get("subject"),
                    "exam_date": r.get("exam_date") or "TBD",
                    "max_marks": r.get("max_marks"),
                }
                for r in rows
            ],
        }
    )
    filename = f"datesheet-{exam_name.replace(' ', '-')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
