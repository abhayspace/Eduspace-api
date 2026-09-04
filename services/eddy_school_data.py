"""Eddy AI — rule-based admin agent.

Handles school data queries (student counts, teacher counts, name lookups,
category breakdowns, etc.) directly from the database. Returns a fully
formatted markdown reply — no LLM needed.

If the message is not a school-data question, returns None so the caller
can fall back to the normal Groq LLM path.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from database import get_client

logger = logging.getLogger("eduspace.eddy.school_data")

ADMIN_ROLES = {"school_admin", "principal", "super_admin", "vice_principal"}


# ===================================================================
# Public entry point
# ===================================================================

async def try_admin_agent(school_id: str, message: str) -> Optional[str]:
    """Attempt to answer an admin school-data question.

    Returns a markdown reply string, or None if this isn't a data query.
    """
    msg = message.lower().strip()

    intent = _detect_intent(msg)
    if intent is None:
        return None

    logger.info("Eddy admin agent: school=%s intent=%s msg=%r", school_id, intent, msg[:100])

    try:
        if intent == "student_count":
            return await _answer_student_count(school_id, msg)
        if intent == "teacher_count":
            return await _answer_teacher_count(school_id, msg)
        if intent == "student_by_name":
            return await _answer_student_by_name(school_id, msg)
        if intent == "student_by_letter":
            return await _answer_student_by_letter(school_id, msg)
        if intent == "student_by_father":
            return await _answer_student_by_father(school_id, msg)
        if intent == "student_by_category":
            return await _answer_student_by_category(school_id, msg)
        if intent == "class_strength":
            return await _answer_class_strength(school_id, msg)
        if intent == "school_overview":
            return await _answer_school_overview(school_id)
    except Exception:
        logger.exception("Eddy admin agent failed for intent=%s", intent)
        return None

    return None


# ===================================================================
# Intent detection
# ===================================================================

def _detect_intent(msg: str) -> Optional[str]:
    # Father name queries (check before generic student)
    if any(k in msg for k in ["father name", "father's name", "whose father", "papa ka naam",
                                "father is", "papa"]):
        return "student_by_father"

    # Category queries
    if any(k in msg for k in ["category", "obc student", "sc student", "st student",
                                "general student", "minor student",
                                "obc category", "sc category", "st category"]):
        return "student_by_category"

    # Name starts with letter
    if any(k in msg for k in ["start from", "start with", "starts with", "starting with",
                                "begin with", "begins with", "name from"]):
        return "student_by_letter"

    # Student name search
    if any(k in msg for k in ["student named", "student name", "students named",
                                "students with name", "student of name",
                                "find student", "search student"]):
        return "student_by_name"

    # Class strength
    if any(k in msg for k in ["class strength", "strength of class", "students in class",
                                "how many in class", "class wise", "classwise"]):
        return "class_strength"

    # Student count
    if any(k in msg for k in ["how many student", "total student", "student count",
                                "number of student", "kitne student", "kitne bachche",
                                "students are there", "students are their",
                                "students in my school", "students in school",
                                "enrolled student"]):
        return "student_count"

    # Teacher / staff count
    if any(k in msg for k in ["how many teacher", "total teacher", "teacher count",
                                "number of teacher", "kitne teacher",
                                "teachers are there", "teachers are their",
                                "how many staff", "total staff", "staff count",
                                "faculty", "employees"]):
        return "teacher_count"

    # Generic overview
    if any(k in msg for k in ["school overview", "school summary", "school stats",
                                "school data", "about my school", "tell me about school"]):
        return "school_overview"

    return None


# ===================================================================
# Data fetchers (shared)
# ===================================================================

async def _load_students(school_id: str):
    """Fetch all students with user info, class/section names."""
    client = get_client()

    stu_res = await (
        client.table("students")
        .select("id,user_id,father_name,mother_name,category,class_id,section_id,gender,guardian_mobile")
        .eq("school_id", school_id)
        .execute()
    )
    profiles = stu_res.data or []
    if not profiles:
        return []

    user_ids = [p["user_id"] for p in profiles if p.get("user_id")]
    users_map: Dict[str, dict] = {}
    # Batch in chunks of 50 to avoid Supabase URL length limits
    for i in range(0, len(user_ids), 50):
        batch = user_ids[i:i + 50]
        users_res = await (
            client.table("users")
            .select("id,full_name,is_active")
            .in_("id", batch)
            .execute()
        )
        for u in (users_res.data or []):
            users_map[u["id"]] = u

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
    return students


async def _load_teachers(school_id: str):
    client = get_client()
    res = await (
        client.table("users")
        .select("id,full_name,is_active,gender")
        .eq("school_id", school_id)
        .eq("role", "teacher")
        .execute()
    )
    return res.data or []


# ===================================================================
# Answer builders
# ===================================================================

def _wants_only_total(msg: str) -> bool:
    short = ["how many", "total", "count", "kitne"]
    detail = ["breakdown", "category", "class wise", "classwise", "gender", "detail", "list"]
    return any(k in msg for k in short) and not any(k in msg for k in detail)


async def _answer_student_count(school_id: str, msg: str) -> str:
    students = await _load_students(school_id)
    total = len(students)
    active = sum(1 for s in students if s["active"])

    if _wants_only_total(msg):
        return f"Your school has {total} students ({active} active)."

    cats = _count_by(students, "category")
    genders = _count_by(students, "gender")
    classes = _count_by(students, "class")

    lines = [f"Your school has {total} students ({active} active).\n"]

    if genders:
        lines.append("Gender-wise:")
        for k, v in sorted(genders.items()):
            lines.append(f"- {k or 'Unknown'}: {v}")
        lines.append("")

    if cats:
        lines.append("Category-wise:")
        for k, v in sorted(cats.items()):
            lines.append(f"- {k or 'Unknown'}: {v}")
        lines.append("")

    if classes:
        lines.append("Class-wise:")
        for k, v in sorted(classes.items()):
            lines.append(f"- {k or 'Unknown'}: {v}")

    return "\n".join(lines)


async def _answer_teacher_count(school_id: str, msg: str) -> str:
    teachers = await _load_teachers(school_id)
    total = len(teachers)
    active = sum(1 for t in teachers if t.get("is_active", True))

    if _wants_only_total(msg):
        return f"Your school has {total} teachers/staff ({active} active)."

    genders: Dict[str, int] = {}
    for t in teachers:
        g = t.get("gender") or "Unknown"
        genders[g] = genders.get(g, 0) + 1

    lines = [f"Your school has {total} teachers/staff ({active} active).\n"]

    if genders:
        lines.append("Gender-wise:")
        for k, v in sorted(genders.items()):
            lines.append(f"- {k or 'Unknown'}: {v}")

    return "\n".join(lines)


async def _answer_student_by_name(school_id: str, msg: str) -> str:
    name_q = _extract_name_query(msg)
    if not name_q:
        return "Please specify a student name to search for."

    students = await _load_students(school_id)
    matches = [s for s in students if name_q in s["name"].lower()]

    if not matches:
        return f"No students found matching \"{name_q}\" in your school."

    lines = [f"Found {len(matches)} student(s) matching \"{name_q}\":\n"]
    for s in matches[:30]:
        lines.append(f"- {s['name']} — Father: {s['father_name']}, Class: {s['class']} {s['section']}, Category: {s['category']}")
    if len(matches) > 30:
        lines.append(f"\n...and {len(matches) - 30} more.")

    return "\n".join(lines)


async def _answer_student_by_letter(school_id: str, msg: str) -> str:
    letter = _extract_letter_query(msg)
    if not letter:
        return "Please specify a letter, e.g. \"students whose name starts with A\"."

    students = await _load_students(school_id)
    matches = [s for s in students if s["name"].lower().startswith(letter)]

    if not matches:
        return f"No students found whose name starts with \"{letter.upper()}\"."

    lines = [f"{len(matches)} student(s) whose name starts with \"{letter.upper()}\":\n"]
    for s in matches[:30]:
        lines.append(f"- {s['name']} — Father: {s['father_name']}, Class: {s['class']} {s['section']}")
    if len(matches) > 30:
        lines.append(f"\n...and {len(matches) - 30} more.")

    return "\n".join(lines)


async def _answer_student_by_father(school_id: str, msg: str) -> str:
    father_q = _extract_father_query(msg)
    if not father_q:
        return "Please specify a father's name to search for."

    students = await _load_students(school_id)
    matches = [s for s in students if father_q in s["father_name"].lower()]

    if not matches:
        return f"No students found with father's name matching \"{father_q}\"."

    lines = [f"Found {len(matches)} student(s) with father's name matching \"{father_q}\":\n"]
    for s in matches[:30]:
        lines.append(f"- {s['name']} — Father: {s['father_name']}, Class: {s['class']} {s['section']}")
    if len(matches) > 30:
        lines.append(f"\n...and {len(matches) - 30} more.")

    return "\n".join(lines)


async def _answer_student_by_category(school_id: str, msg: str) -> str:
    cat_q = _extract_category_query(msg)
    students = await _load_students(school_id)

    if cat_q:
        matches = [s for s in students if s["category"].lower() == cat_q]
        if not matches:
            return f"No students found in {cat_q.upper()} category."

        lines = [f"{len(matches)} student(s) in {cat_q.upper()} category:\n"]
        for s in matches[:30]:
            lines.append(f"- {s['name']} — Father: {s['father_name']}, Class: {s['class']} {s['section']}")
        if len(matches) > 30:
            lines.append(f"\n...and {len(matches) - 30} more.")
        return "\n".join(lines)

    cats = _count_by(students, "category")
    lines = [f"Category-wise breakdown ({len(students)} total students):\n"]
    for k, v in sorted(cats.items()):
        lines.append(f"- {k or 'Unknown'}: {v}")
    return "\n".join(lines)


async def _answer_class_strength(school_id: str, msg: str) -> str:
    students = await _load_students(school_id)
    classes = _count_by(students, "class")

    lines = [f"Class-wise student strength ({len(students)} total):\n"]
    for k, v in sorted(classes.items()):
        lines.append(f"- {k or 'Unknown'}: {v} students")

    return "\n".join(lines)


async def _answer_school_overview(school_id: str) -> str:
    students = await _load_students(school_id)
    teachers = await _load_teachers(school_id)

    total_stu = len(students)
    active_stu = sum(1 for s in students if s["active"])
    total_tea = len(teachers)
    active_tea = sum(1 for t in teachers if t.get("is_active", True))
    cats = _count_by(students, "category")
    classes = _count_by(students, "class")

    lines = [
        f"Here's an overview of your school:\n",
        f"Students: {total_stu} ({active_stu} active)",
    ]
    for k, v in sorted(cats.items()):
        lines.append(f"- {k or 'Unknown'}: {v}")
    lines.append("")
    lines.append("Class-wise:")
    for k, v in sorted(classes.items()):
        lines.append(f"- {k or 'Unknown'}: {v}")
    lines.append(f"\nTeachers/Staff: {total_tea} ({active_tea} active)")

    return "\n".join(lines)


# ===================================================================
# Helpers
# ===================================================================

def _count_by(items: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        val = item.get(key) or "Unknown"
        counts[val] = counts.get(val, 0) + 1
    return counts


def _extract_name_query(msg: str) -> Optional[str]:
    patterns = [
        "students named ", "student named ", "students with name ",
        "student with name ", "students of name ", "student of name ",
        "find student ", "search student ", "named ",
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


def _extract_letter_query(msg: str) -> Optional[str]:
    """Extract the letter from 'name starts with A' style queries."""
    patterns = [
        "start from ", "start with ", "starts with ", "starting with ",
        "begin with ", "begins with ", "name from ",
    ]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            if rest:
                return rest[0].lower()
    return None


def _extract_father_query(msg: str) -> Optional[str]:
    patterns = [
        "father name is ", "father's name is ", "father name ",
        "father's name ", "whose father ", "papa ka naam ",
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
    for cat in categories:
        if f"category {cat}" in msg or f"{cat} category" in msg or f"of {cat}" in msg or f"{cat} student" in msg:
            return cat
    return None
