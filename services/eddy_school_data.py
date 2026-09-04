"""Eddy AI — school data context for admin queries.

Fetches live school statistics (student counts, teacher counts, category
breakdowns, name/father-name lookups) so the LLM can answer admin
questions with real data.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from database import get_client

logger = logging.getLogger("eduspace.eddy.school_data")

ADMIN_ROLES = {"school_admin", "principal", "super_admin", "vice_principal"}


async def fetch_school_context(school_id: str, message: str) -> str:
    """Return a data-context string to inject into the system prompt.

    Only runs real DB queries when the message seems to ask about school data.
    Returns an empty string if nothing relevant is detected.
    """
    msg = message.lower()

    needs_students = _mentions_students(msg)
    needs_teachers = _mentions_teachers(msg)

    logger.info("Eddy school context: school=%s students=%s teachers=%s msg=%r",
                school_id, needs_students, needs_teachers, msg[:100])

    if not needs_students and not needs_teachers:
        return ""

    parts: List[str] = []

    try:
        if needs_students:
            parts.append(await _student_context(school_id, msg))
        if needs_teachers:
            parts.append(await _teacher_context(school_id, msg))
    except Exception:
        logger.exception("Failed to fetch school context for Eddy")
        return ""

    context = "\n".join(p for p in parts if p)
    if not context:
        return ""

    return (
        "\n\n--- SCHOOL DATA (live from database, use this to answer) ---\n"
        + context
        + "\n--- END SCHOOL DATA ---\n"
    )


# ---------------------------------------------------------------------------
# Keyword detection
# ---------------------------------------------------------------------------

_STUDENT_KEYWORDS = [
    "student", "students", "how many student", "total student",
    "father name", "father's name", "category", "obc", "general", " sc ", " st ",
    "class", "section", "admission", "enrolled", "strength",
]

_TEACHER_KEYWORDS = [
    "teacher", "teachers", "staff", "how many teacher", "total teacher",
    "faculty", "employee",
]


def _mentions_students(msg: str) -> bool:
    return any(kw in msg for kw in _STUDENT_KEYWORDS)


def _mentions_teachers(msg: str) -> bool:
    return any(kw in msg for kw in _TEACHER_KEYWORDS)


# ---------------------------------------------------------------------------
# Student context
# ---------------------------------------------------------------------------

async def _student_context(school_id: str, msg: str) -> str:
    client = get_client()

    # Fetch all students with their user info
    stu_res = await (
        client.table("students")
        .select("id,user_id,father_name,mother_name,category,class_id,section_id,gender,guardian_mobile")
        .eq("school_id", school_id)
        .execute()
    )
    profiles = stu_res.data or []

    if not profiles:
        return "Total students in the school: 0"

    user_ids = [p["user_id"] for p in profiles if p.get("user_id")]
    users_res = await (
        client.table("users")
        .select("id,full_name,is_active")
        .in_("id", user_ids)
        .execute()
    )
    users_map: Dict[str, dict] = {u["id"]: u for u in (users_res.data or [])}

    # Resolve class/section names
    class_ids = list({p["class_id"] for p in profiles if p.get("class_id")})
    section_ids = list({p["section_id"] for p in profiles if p.get("section_id")})
    class_map: Dict[str, str] = {}
    section_map: Dict[str, str] = {}
    if class_ids:
        cls_res = await client.table("classes").select("id,name").in_("id", class_ids).execute()
        class_map = {c["id"]: c["name"] for c in (cls_res.data or [])}
    if section_ids:
        sec_res = await client.table("sections").select("id,name").in_("id", section_ids).execute()
        section_map = {s["id"]: s["name"] for s in (sec_res.data or [])}

    # Build enriched list
    students: List[Dict[str, Any]] = []
    for p in profiles:
        user = users_map.get(p.get("user_id", ""))
        if not user:
            continue
        students.append({
            "name": user.get("full_name", ""),
            "active": user.get("is_active", True),
            "father_name": p.get("father_name") or "",
            "mother_name": p.get("mother_name") or "",
            "category": p.get("category") or "",
            "gender": p.get("gender") or "",
            "class": class_map.get(p.get("class_id", ""), ""),
            "section": section_map.get(p.get("section_id", ""), ""),
        })

    total = len(students)
    active = sum(1 for s in students if s["active"])

    lines = [f"Total students: {total} (active: {active})"]

    # Category breakdown
    cats: Dict[str, int] = {}
    for s in students:
        c = s["category"] or "Unknown"
        cats[c] = cats.get(c, 0) + 1
    if cats:
        lines.append("Category breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(cats.items())))

    # Gender breakdown
    genders: Dict[str, int] = {}
    for s in students:
        g = s["gender"] or "Unknown"
        genders[g] = genders.get(g, 0) + 1
    if genders:
        lines.append("Gender breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(genders.items())))

    # Class-wise breakdown
    class_counts: Dict[str, int] = {}
    for s in students:
        cn = s["class"] or "Unknown"
        class_counts[cn] = class_counts.get(cn, 0) + 1
    if class_counts:
        lines.append("Class-wise: " + ", ".join(f"{k}: {v}" for k, v in sorted(class_counts.items())))

    # If asking about a specific name
    name_query = _extract_name_query(msg, "student")
    if name_query:
        matches = [s for s in students if name_query in s["name"].lower()]
        if matches:
            lines.append(f"\nStudents matching name '{name_query}':")
            for s in matches[:20]:
                lines.append(
                    f"  - {s['name']} | Father: {s['father_name']} | Class: {s['class']} {s['section']} | Category: {s['category']}"
                )
        else:
            lines.append(f"\nNo students found matching name '{name_query}'.")

    # If asking about father's name
    father_query = _extract_father_query(msg)
    if father_query:
        matches = [s for s in students if father_query in s["father_name"].lower()]
        if matches:
            lines.append(f"\nStudents with father's name matching '{father_query}':")
            for s in matches[:20]:
                lines.append(
                    f"  - {s['name']} | Father: {s['father_name']} | Class: {s['class']} {s['section']}"
                )
        else:
            lines.append(f"\nNo students found with father's name matching '{father_query}'.")

    # If asking about a specific category
    cat_query = _extract_category_query(msg)
    if cat_query:
        matches = [s for s in students if s["category"].lower() == cat_query]
        lines.append(f"\nStudents in category '{cat_query.upper()}': {len(matches)}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Teacher context
# ---------------------------------------------------------------------------

async def _teacher_context(school_id: str, msg: str) -> str:
    client = get_client()

    teacher_res = await (
        client.table("users")
        .select("id,full_name,is_active,gender")
        .eq("school_id", school_id)
        .eq("role", "teacher")
        .execute()
    )
    teachers = teacher_res.data or []
    total = len(teachers)
    active = sum(1 for t in teachers if t.get("is_active", True))

    lines = [f"Total teachers/staff: {total} (active: {active})"]

    genders: Dict[str, int] = {}
    for t in teachers:
        g = t.get("gender") or "Unknown"
        genders[g] = genders.get(g, 0) + 1
    if genders:
        lines.append("Gender breakdown: " + ", ".join(f"{k}: {v}" for k, v in sorted(genders.items())))

    # Name search
    name_query = _extract_name_query(msg, "teacher")
    if name_query:
        matches = [t for t in teachers if name_query in t["full_name"].lower()]
        if matches:
            lines.append(f"\nTeachers matching '{name_query}':")
            for t in matches[:20]:
                lines.append(f"  - {t['full_name']}")
        else:
            lines.append(f"\nNo teachers found matching '{name_query}'.")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Query extraction helpers
# ---------------------------------------------------------------------------

def _extract_name_query(msg: str, entity: str) -> Optional[str]:
    """Try to pull out a name the user is searching for."""
    patterns = [
        f"{entity}s named ", f"{entity}s with name ", f"{entity} named ",
        f"{entity} with name ", f"{entity}s of name ", f"name is ",
        f"name ", f"named ",
    ]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            # Take first few words as the name
            words = rest.split()[:3]
            name = " ".join(words).strip("?.,! ")
            if name:
                return name.lower()
    return None


def _extract_father_query(msg: str) -> Optional[str]:
    patterns = [
        "father name is ", "father's name is ", "father name ",
        "father's name ", "whose father ",
    ]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            words = rest.split()[:3]
            name = " ".join(words).strip("?.,! ")
            if name:
                return name.lower()
    return None


def _extract_category_query(msg: str) -> Optional[str]:
    categories = ["general", "obc", "sc", "st", "minor"]
    # Check if asking about a specific category
    for cat in categories:
        if f"category {cat}" in msg or f"{cat} category" in msg or f"of {cat}" in msg:
            return cat
    return None
