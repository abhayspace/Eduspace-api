"""Examination results — upload, report card, analytics."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from database import get_client
from schemas.content import ResultBulkIn, ResultBulkOut, ResultItem
from services.exam_pdf import generate_report_card_pdf
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/results", tags=["results"])

_COLUMNS = "id,school_id,examination_id,student_email,marks_obtained,grade"
_EXAM_COLUMNS = "id,school_id,name,term,class_name,subject,exam_date,max_marks"


def _grade_for(marks: float, max_marks: float) -> str:
    if max_marks <= 0:
        return "—"
    pct = (marks / max_marks) * 100
    if pct >= 90:
        return "A+"
    if pct >= 80:
        return "A"
    if pct >= 70:
        return "B+"
    if pct >= 60:
        return "B"
    if pct >= 50:
        return "C"
    if pct >= 40:
        return "D"
    return "E"


@router.get("/me", response_model=List[ResultItem])
async def my_results(user: dict = Depends(current_user)) -> List[ResultItem]:
    client = get_client()
    res = (
        await client.table("results")
        .select(_COLUMNS)
        .eq("school_id", user["school_id"])
        .eq("student_email", user["email"])
        .limit(200)
        .execute()
    )
    return [ResultItem(**row) for row in (res.data or [])]


@router.get("", response_model=List[ResultItem])
async def list_results(
    examination_id: Optional[str] = Query(default=None),
    student_email: Optional[str] = Query(default=None),
    exam_name: Optional[str] = Query(default=None),
    user: dict = Depends(require_roles("school_admin", "principal", "teacher")),
) -> List[ResultItem]:
    client = get_client()
    school_id = user["school_id"]
    exam_ids: Optional[List[str]] = None
    if exam_name:
        exams = (
            await client.table("examinations")
            .select("id")
            .eq("school_id", school_id)
            .eq("name", exam_name)
            .limit(500)
            .execute()
        )
        exam_ids = [r["id"] for r in (exams.data or []) if r.get("id")]
        if not exam_ids:
            return []

    q = client.table("results").select(_COLUMNS).eq("school_id", school_id)
    if examination_id:
        q = q.eq("examination_id", examination_id)
    if student_email:
        q = q.eq("student_email", student_email)
    if exam_ids is not None:
        q = q.in_("examination_id", exam_ids)
    res = await q.limit(1000).execute()
    return [ResultItem(**row) for row in (res.data or [])]


@router.post("", response_model=ResultItem)
async def create_result(
    body: ResultItem,
    user: dict = Depends(require_roles("school_admin", "principal", "teacher")),
) -> ResultItem:
    client = get_client()
    grade = body.grade
    if not grade and body.examination_id:
        exam = (
            await client.table("examinations")
            .select("max_marks")
            .eq("id", body.examination_id)
            .limit(1)
            .execute()
        )
        max_marks = float((exam.data or [{}])[0].get("max_marks") or 100)
        grade = _grade_for(body.marks_obtained, max_marks)
    row = {
        "school_id": user["school_id"],
        "examination_id": body.examination_id,
        "student_email": body.student_email,
        "marks_obtained": body.marks_obtained,
        "grade": grade,
    }
    inserted = await client.table("results").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create result")
    return ResultItem(**inserted.data[0])


@router.post("/bulk", response_model=ResultBulkOut)
async def create_results_bulk(
    body: ResultBulkIn,
    user: dict = Depends(require_roles("school_admin", "principal", "teacher")),
) -> ResultBulkOut:
    client = get_client()
    school_id = user["school_id"]
    exam_ids = list({item.examination_id for item in body.items})
    exams = (
        await client.table("examinations")
        .select("id,max_marks")
        .eq("school_id", school_id)
        .in_("id", exam_ids)
        .execute()
    )
    max_map = {r["id"]: float(r.get("max_marks") or 100) for r in (exams.data or [])}

    rows = []
    for item in body.items:
        max_marks = max_map.get(item.examination_id, 100.0)
        rows.append(
            {
                "school_id": school_id,
                "examination_id": item.examination_id,
                "student_email": item.student_email,
                "marks_obtained": item.marks_obtained,
                "grade": item.grade or _grade_for(item.marks_obtained, max_marks),
            }
        )
    inserted = await client.table("results").insert(rows).execute()
    created = [ResultItem(**row) for row in (inserted.data or [])]
    return ResultBulkOut(created=len(created), results=created)


@router.get("/report-card/pdf")
async def download_report_card_pdf(
    exam_name: str = Query(...),
    student_email: str = Query(...),
    user: dict = Depends(require_roles("school_admin", "principal", "teacher")),
) -> Response:
    client = get_client()
    school_id = user["school_id"]

    exams = (
        await client.table("examinations")
        .select(_EXAM_COLUMNS)
        .eq("school_id", school_id)
        .eq("name", exam_name)
        .limit(200)
        .execute()
    )
    exam_rows = exams.data or []
    if not exam_rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Examination not found")
    exam_ids = [e["id"] for e in exam_rows]
    exam_by_id = {e["id"]: e for e in exam_rows}

    results = (
        await client.table("results")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("student_email", student_email)
        .in_("examination_id", exam_ids)
        .limit(200)
        .execute()
    )
    student_results = results.data or []
    if not student_results:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No marks found for this student")

    all_results = (
        await client.table("results")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .in_("examination_id", exam_ids)
        .limit(2000)
        .execute()
    )
    by_exam: Dict[str, List[float]] = defaultdict(list)
    for row in all_results.data or []:
        eid = row.get("examination_id")
        if eid:
            by_exam[eid].append(float(row.get("marks_obtained") or 0))

    users = (
        await client.table("users")
        .select("id,full_name,email")
        .eq("school_id", school_id)
        .eq("email", student_email)
        .limit(1)
        .execute()
    )
    user_row = (users.data or [{}])[0]
    student_profile = {}
    if user_row.get("id"):
        st = (
            await client.table("students")
            .select("class_id,section_id")
            .eq("user_id", user_row["id"])
            .limit(1)
            .execute()
        )
        student_profile = (st.data or [{}])[0]

    class_name = ""
    section_name = ""
    if student_profile.get("class_id"):
        cls = (
            await client.table("classes")
            .select("name")
            .eq("id", student_profile["class_id"])
            .limit(1)
            .execute()
        )
        class_name = ((cls.data or [{}])[0].get("name")) or ""
    if student_profile.get("section_id"):
        sec = (
            await client.table("sections")
            .select("name")
            .eq("id", student_profile["section_id"])
            .limit(1)
            .execute()
        )
        section_name = ((sec.data or [{}])[0].get("name")) or ""

    # Prefer class from first exam row if student profile missing
    if not class_name:
        class_name = exam_rows[0].get("class_name") or ""

    school_res = (
        await client.table("schools")
        .select("school_name,name,city")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    school = (school_res.data or [{}])[0]

    subjects = []
    for row in student_results:
        exam = exam_by_id.get(row.get("examination_id") or "", {})
        eid = row.get("examination_id") or ""
        marks_list = by_exam.get(eid) or []
        avg = (sum(marks_list) / len(marks_list)) if marks_list else None
        subjects.append(
            {
                "subject": exam.get("subject") or "—",
                "marks_obtained": row.get("marks_obtained"),
                "max_marks": exam.get("max_marks") or 100,
                "grade": row.get("grade"),
                "class_average": avg,
            }
        )

    pdf = generate_report_card_pdf(
        {
            "school": school,
            "exam_name": exam_name,
            "student": {
                "full_name": user_row.get("full_name") or student_email,
                "class_name": class_name,
                "section_name": section_name,
            },
            "subjects": subjects,
        }
    )
    safe_name = (user_row.get("full_name") or "student").replace(" ", "-")
    filename = f"report-card-{safe_name}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/analytics")
async def results_analytics(
    exam_name: str = Query(...),
    class_name: Optional[str] = Query(default=None),
    user: dict = Depends(require_roles("school_admin", "principal", "teacher")),
) -> dict:
    client = get_client()
    school_id = user["school_id"]
    q = (
        client.table("examinations")
        .select(_EXAM_COLUMNS)
        .eq("school_id", school_id)
        .eq("name", exam_name)
    )
    if class_name:
        q = q.eq("class_name", class_name)
    exams = await q.limit(500).execute()
    exam_rows = exams.data or []
    if not exam_rows:
        return {
            "exam_name": exam_name,
            "top_students": [],
            "subject_rings": [],
            "class_comparison": [],
            "student_comparison": [],
        }

    exam_ids = [e["id"] for e in exam_rows]
    exam_by_id = {e["id"]: e for e in exam_rows}

    results = (
        await client.table("results")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .in_("examination_id", exam_ids)
        .limit(2000)
        .execute()
    )
    result_rows = results.data or []

    # Totals per student
    student_totals: Dict[str, float] = defaultdict(float)
    student_counts: Dict[str, int] = defaultdict(int)
    subject_marks: Dict[str, List[float]] = defaultdict(list)
    class_totals: Dict[str, List[float]] = defaultdict(list)

    for row in result_rows:
        email = row.get("student_email") or ""
        marks = float(row.get("marks_obtained") or 0)
        eid = row.get("examination_id") or ""
        exam = exam_by_id.get(eid, {})
        subject = exam.get("subject") or "—"
        cls = exam.get("class_name") or "—"
        student_totals[email] += marks
        student_counts[email] += 1
        subject_marks[subject].append(marks)
        class_totals[cls].append(marks)

    emails = list(student_totals.keys())
    name_map: Dict[str, str] = {}
    if emails:
        users = (
            await client.table("users")
            .select("email,full_name")
            .eq("school_id", school_id)
            .in_("email", emails[:200])
            .execute()
        )
        name_map = {u["email"]: u.get("full_name") or u["email"] for u in (users.data or [])}

    ranked = sorted(student_totals.items(), key=lambda kv: kv[1], reverse=True)
    top_students = [
        {
            "student_email": email,
            "full_name": name_map.get(email, email),
            "total_marks": round(total, 2),
            "subjects_count": student_counts[email],
            "average": round(total / max(student_counts[email], 1), 2),
        }
        for email, total in ranked[:10]
    ]

    subject_rings = []
    for subject, marks in sorted(subject_marks.items()):
        avg = sum(marks) / len(marks) if marks else 0
        # Assume max 100 for ring fill unless we know otherwise
        subject_rings.append(
            {
                "subject": subject,
                "average": round(avg, 2),
                "count": len(marks),
                "pct": round(min(100, (avg / 100) * 100), 1),
            }
        )

    class_comparison = [
        {
            "class_name": cls,
            "average": round(sum(vals) / len(vals), 2) if vals else 0,
            "count": len(vals),
        }
        for cls, vals in sorted(class_totals.items())
    ]

    student_comparison = [
        {
            "student_email": email,
            "full_name": name_map.get(email, email),
            "total_marks": round(total, 2),
            "average": round(total / max(student_counts[email], 1), 2),
        }
        for email, total in ranked[:20]
    ]

    return {
        "exam_name": exam_name,
        "top_students": top_students,
        "subject_rings": subject_rings,
        "class_comparison": class_comparison,
        "student_comparison": student_comparison,
    }
