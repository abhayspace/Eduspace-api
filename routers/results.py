"""Examination results — upload, report card, analytics."""
from __future__ import annotations

import hashlib
import random
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

# Demo / QA schools that should always see sample teacher analytics.
_DEMO_INSTITUTION_CODES = {"KCPSCH"}


async def _school_institution_code(school_id: str) -> str:
    client = get_client()
    res = (
        await client.table("schools")
        .select("institution_code")
        .eq("id", school_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return ""
    return (res.data[0].get("institution_code") or "").strip().upper()


async def _is_demo_performance_school(school_id: str) -> bool:
    return await _school_institution_code(school_id) in _DEMO_INSTITUTION_CODES


def _demo_rng(*parts: str) -> random.Random:
    digest = hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()
    return random.Random(int(digest[:8], 16))


def _demo_teacher_performance_options() -> dict:
    subjects = ["Mathematics", "Science", "English"]
    exams = [
        {
            "name": "Mid Term Examination",
            "exam_date": "2026-07-15",
            "subjects": subjects,
        },
        {
            "name": "Unit Test 2",
            "exam_date": "2026-06-20",
            "subjects": subjects,
        },
        {
            "name": "Unit Test 1",
            "exam_date": "2026-05-10",
            "subjects": subjects,
        },
    ]
    return {
        "exams": exams,
        "subjects": subjects,
        "default_exam": exams[0]["name"],
        "default_subject": subjects[0],
        "classes": ["8A", "8B", "9A", "9B"],
    }


def _demo_teacher_performance(exam_name: str, subject: str) -> dict:
    """Stable pseudo-random sample analytics for demo schools (varies by filters)."""
    exam_key = (exam_name or "Mid Term Examination").strip() or "Mid Term Examination"
    subject_key = (subject or "Mathematics").strip() or "Mathematics"
    rng = _demo_rng("kcpsch-demo", exam_key, subject_key)
    class_names = ["8A", "8B", "9A", "9B"]

    class_bars = []
    all_pcts: List[float] = []
    total_students = 0
    for cls in class_names:
        avg = round(rng.uniform(68.0, 94.0), 1)
        count = rng.randint(22, 36)
        high = round(min(99.5, avg + rng.uniform(4.0, 12.0)), 1)
        low = round(max(38.0, avg - rng.uniform(16.0, 32.0)), 1)
        class_bars.append(
            {
                "class_name": cls,
                "average_pct": avg,
                "student_count": count,
                "highest_pct": high,
                "lowest_pct": low,
            }
        )
        # Approximate student score pool for overall high/low
        for _ in range(count):
            all_pcts.append(round(rng.uniform(low, high), 1))
        total_students += count

    best = max(class_bars, key=lambda row: row["average_pct"])
    lowest = min(class_bars, key=lambda row: row["average_pct"])
    overall = round(sum(b["average_pct"] for b in class_bars) / len(class_bars), 1)
    highest = round(max(all_pcts), 1) if all_pcts else 0
    lowest_score = round(min(all_pcts), 1) if all_pcts else 0
    gap = round(best["average_pct"] - lowest["average_pct"], 1)
    insight = (
        f"Class {best['class_name']} achieved the highest average score "
        f"({best['average_pct']}%). Class {lowest['class_name']} scored "
        f"{gap}% lower than the top-performing class and may benefit from "
        f"additional revision before the next assessment."
    )
    return {
        "exam_name": exam_key,
        "subject": subject_key,
        "class_bars": class_bars,
        "best_class": {
            "class_name": best["class_name"],
            "average_pct": best["average_pct"],
        },
        "lowest_class": {
            "class_name": lowest["class_name"],
            "average_pct": lowest["average_pct"],
        },
        "overall_average": overall,
        "highest_score": highest,
        "lowest_score": lowest_score,
        "total_students": total_students,
        "insight": insight,
    }


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


def _teacher_class_names(assignments: list) -> list[str]:
    """Unique class names from entries like '8 - A' / '8 - All Sections'."""
    names: set[str] = set()
    for entry in assignments or []:
        raw = (entry or "").strip()
        if not raw:
            continue
        names.add(raw)
        class_name = raw.split(" - ", 1)[0].strip()
        if class_name:
            names.add(class_name)
        if " - " in raw:
            base, section = raw.split(" - ", 1)
            base = base.strip()
            section = section.strip()
            if base and section and section.lower() not in ("all sections", "all"):
                names.add(f"{base}{section}")
                names.add(f"{base} {section}")
    return sorted(names, key=lambda value: value.lower())


@router.get("/teacher-performance/options")
async def teacher_performance_options(
    user: dict = Depends(require_roles("teacher")),
) -> dict:
    """Exams + subjects available for the logged-in teacher's classes."""
    from services import teacher_service

    client = get_client()
    school_id = user["school_id"]
    if await _is_demo_performance_school(school_id):
        return _demo_teacher_performance_options()

    teacher = await teacher_service.get_teacher_by_user_id(school_id, user["id"])
    allowed_classes = _teacher_class_names(teacher.classes_teaching or [])
    subjects = sorted(
        {str(s).strip() for s in (teacher.subjects or []) if str(s).strip()},
        key=lambda value: value.lower(),
    )

    if not allowed_classes:
        return {
            "exams": [],
            "subjects": subjects,
            "default_exam": None,
            "default_subject": subjects[0] if subjects else None,
            "classes": [],
        }

    exams_res = (
        await client.table("examinations")
        .select("name,class_name,subject,exam_date")
        .eq("school_id", school_id)
        .in_("class_name", allowed_classes)
        .order("exam_date", desc=True)
        .limit(1000)
        .execute()
    )
    rows = exams_res.data or []
    if subjects:
        subject_keys = {s.lower() for s in subjects}
        rows = [r for r in rows if (r.get("subject") or "").strip().lower() in subject_keys]

    exam_meta: Dict[str, dict] = {}
    subjects_from_exams: set[str] = set()
    for row in rows:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        bucket = exam_meta.setdefault(
            name,
            {"name": name, "exam_date": row.get("exam_date"), "subjects": set()},
        )
        subject = (row.get("subject") or "").strip()
        if subject:
            bucket["subjects"].add(subject)
            subjects_from_exams.add(subject)
        # Prefer the latest non-null exam_date
        if row.get("exam_date") and (
            not bucket.get("exam_date") or str(row["exam_date"]) > str(bucket["exam_date"])
        ):
            bucket["exam_date"] = row["exam_date"]

    exams = sorted(
        [
            {
                "name": data["name"],
                "exam_date": data.get("exam_date"),
                "subjects": sorted(data["subjects"]),
            }
            for data in exam_meta.values()
        ],
        key=lambda item: (item.get("exam_date") or "", item["name"]),
        reverse=True,
    )

    if not subjects:
        subjects = sorted(subjects_from_exams, key=lambda value: value.lower())

    default_exam = exams[0]["name"] if exams else None
    default_subject = subjects[0] if subjects else None
    if default_exam and not default_subject:
        exam_subjects = exams[0].get("subjects") or []
        default_subject = exam_subjects[0] if exam_subjects else None

    return {
        "exams": exams,
        "subjects": subjects,
        "default_exam": default_exam,
        "default_subject": default_subject,
        "classes": allowed_classes,
    }


@router.get("/teacher-performance")
async def teacher_performance(
    exam_name: str = Query(...),
    subject: str = Query(...),
    user: dict = Depends(require_roles("teacher")),
) -> dict:
    """Class-level performance for one exam + subject across a teacher's classes."""
    from services import teacher_service

    client = get_client()
    school_id = user["school_id"]
    subject_key = subject.strip()
    exam_key = exam_name.strip()
    if await _is_demo_performance_school(school_id):
        return _demo_teacher_performance(exam_key, subject_key)

    teacher = await teacher_service.get_teacher_by_user_id(school_id, user["id"])
    allowed_classes = _teacher_class_names(teacher.classes_teaching or [])

    empty = {
        "exam_name": exam_key,
        "subject": subject_key,
        "class_bars": [],
        "best_class": None,
        "lowest_class": None,
        "overall_average": 0,
        "highest_score": 0,
        "lowest_score": 0,
        "total_students": 0,
        "insight": "No performance data is available for this exam and subject yet.",
    }

    if not allowed_classes or not exam_key or not subject_key:
        return empty

    exams = (
        await client.table("examinations")
        .select(_EXAM_COLUMNS)
        .eq("school_id", school_id)
        .eq("name", exam_key)
        .eq("subject", subject_key)
        .in_("class_name", allowed_classes)
        .limit(500)
        .execute()
    )
    exam_rows = exams.data or []
    if not exam_rows:
        return empty

    exam_ids = [e["id"] for e in exam_rows]
    exam_by_id = {e["id"]: e for e in exam_rows}

    results = (
        await client.table("results")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .in_("examination_id", exam_ids)
        .limit(5000)
        .execute()
    )
    result_rows = results.data or []
    if not result_rows:
        return empty

    # Percentages per class (marks / max_marks * 100)
    class_pcts: Dict[str, List[float]] = defaultdict(list)
    all_pcts: List[float] = []
    for row in result_rows:
        eid = row.get("examination_id") or ""
        exam = exam_by_id.get(eid) or {}
        cls = (exam.get("class_name") or "—").strip() or "—"
        max_marks = float(exam.get("max_marks") or 100) or 100
        marks = float(row.get("marks_obtained") or 0)
        pct = max(0.0, min(100.0, (marks / max_marks) * 100))
        class_pcts[cls].append(pct)
        all_pcts.append(pct)

    class_bars = []
    for cls, pcts in sorted(class_pcts.items(), key=lambda kv: kv[0].lower()):
        avg = sum(pcts) / len(pcts) if pcts else 0
        class_bars.append(
            {
                "class_name": cls,
                "average_pct": round(avg, 1),
                "student_count": len(pcts),
                "highest_pct": round(max(pcts), 1) if pcts else 0,
                "lowest_pct": round(min(pcts), 1) if pcts else 0,
            }
        )

    if not class_bars:
        return empty

    best = max(class_bars, key=lambda row: row["average_pct"])
    lowest = min(class_bars, key=lambda row: row["average_pct"])
    overall = round(sum(all_pcts) / len(all_pcts), 1) if all_pcts else 0
    highest = round(max(all_pcts), 1) if all_pcts else 0
    lowest_score = round(min(all_pcts), 1) if all_pcts else 0
    gap = round(best["average_pct"] - lowest["average_pct"], 1)

    if best["class_name"] == lowest["class_name"]:
        insight = (
            f"Class {best['class_name']} averaged {best['average_pct']}% in {subject_key}. "
            f"Overall average across evaluated students is {overall}%."
        )
    else:
        insight = (
            f"Class {best['class_name']} achieved the highest average score "
            f"({best['average_pct']}%). Class {lowest['class_name']} scored "
            f"{gap}% lower than the top-performing class and may benefit from "
            f"additional revision before the next assessment."
        )

    return {
        "exam_name": exam_key,
        "subject": subject_key,
        "class_bars": class_bars,
        "best_class": {
            "class_name": best["class_name"],
            "average_pct": best["average_pct"],
        },
        "lowest_class": {
            "class_name": lowest["class_name"],
            "average_pct": lowest["average_pct"],
        },
        "overall_average": overall,
        "highest_score": highest,
        "lowest_score": lowest_score,
        "total_students": len(all_pcts),
        "insight": insight,
    }
