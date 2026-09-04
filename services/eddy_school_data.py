"""Eddy AI — rule-based admin agent.

Handles school data queries (student counts, teacher counts, name lookups,
category breakdowns, etc.) directly from the database. Returns a fully
formatted markdown reply — no LLM needed.

If the message is not a school-data question, returns None so the caller
can fall back to the normal Groq LLM path.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from config import get_settings
from database import get_client

logger = logging.getLogger("eduspace.eddy.school_data")

ADMIN_ROLES = {"school_admin", "principal", "super_admin", "vice_principal"}


# ===================================================================
# Public entry point
# ===================================================================

async def try_admin_agent(school_id: str, message: str, user: Optional[Dict] = None) -> Optional[str]:
    """Attempt to answer an admin school-data question.

    Returns a markdown reply string, or None if this isn't a data query.
    """
    msg = message.lower().strip()
    user = user or {}

    intent = _detect_intent(msg)
    if intent is None:
        return None

    logger.info("Eddy admin agent: school=%s intent=%s msg=%r", school_id, intent, msg[:100])

    try:
        if intent == "student_count":
            return await _answer_student_count(school_id, msg)
        if intent == "teacher_count":
            return await _answer_teacher_count(school_id, msg)
        if intent == "student_search":
            return await _answer_student_search(school_id, msg)
        if intent == "student_by_name":
            return await _answer_student_by_name(school_id, msg)
        if intent == "student_by_letter":
            return await _answer_student_by_letter(school_id, msg)
        if intent == "student_by_father":
            return await _answer_student_by_father(school_id, msg)
        if intent == "student_by_category":
            return await _answer_student_by_category(school_id, msg)
        if intent == "student_phone":
            return await _answer_student_phone(school_id, msg)
        if intent == "class_strength":
            return await _answer_class_strength(school_id, msg)
        if intent == "school_overview":
            return await _answer_school_overview(school_id)
        if intent == "send_announcement":
            return await _answer_send_announcement(school_id, message, user)
        if intent == "add_calendar_event":
            return await _answer_add_calendar_event(school_id, message, user)
        if intent == "fee_summary":
            return await _answer_fee_summary(school_id)
        if intent == "expense_summary":
            return await _answer_expense_summary(school_id)
    except Exception:
        logger.exception("Eddy admin agent failed for intent=%s", intent)
        return None

    return None


# ===================================================================
# Intent detection
# ===================================================================

def _detect_intent(msg: str) -> Optional[str]:
    # Phone / contact lookup (check early)
    if any(k in msg for k in ["phone number", "mobile number", "contact number",
                                "phone of", "mobile of", "contact of",
                                "guardian number", "parent number", "parent contact",
                                "guardian mobile", "parent mobile", "phone no"]):
        return "student_phone"

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

    # Generic search — "search students with name X", "search X"
    if any(k in msg for k in ["search student", "search for student", "look up student",
                                "find student", "lookup student"]):
        return "student_search"

    # Student name search
    if any(k in msg for k in ["student named", "student name", "students named",
                                "students with name", "student of name",
                                "students of name"]):
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

    # Announcement
    if any(k in msg for k in ["send announcement", "create announcement", "make announcement",
                                "announce to all", "send notice", "broadcast message",
                                "send this announcement", "announcement to all"]):
        return "send_announcement"

    # Calendar event / holiday
    if any(k in msg for k in ["add holiday", "add event", "add to calendar",
                                "create holiday", "create event", "mark holiday",
                                "school holiday", "add special day", "calendar event"]):
        return "add_calendar_event"

    # Fee summary
    if any(k in msg for k in ["fee summary", "fees summary", "total due", "total fees",
                                "pending fees", "fee collection", "fees due",
                                "unpaid fees", "paid this month", "fee status",
                                "how much fee", "kitne fees", "fees collected"]):
        return "fee_summary"

    # Expense / income summary
    if any(k in msg for k in ["expense summary", "expenses summary", "income summary",
                                "total expense", "total income", "profit",
                                "income and expense", "expense report", "spending",
                                "school expenses", "school income", "this month expense",
                                "this month income"]):
        return "expense_summary"

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
            "phone": p.get("guardian_mobile") or "",
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


async def _answer_student_search(school_id: str, msg: str) -> str:
    """Generic search: 'search student Rahul', 'find student Kumar'."""
    query = _extract_search_query(msg)
    if not query:
        return "Please tell me the student name you want to search."

    students = await _load_students(school_id)
    matches = [s for s in students if query in s["name"].lower()]

    if not matches:
        return f"No students found matching \"{query}\" in your school."

    lines = [f"Found {len(matches)} student(s) matching \"{query}\":\n"]
    for s in matches[:30]:
        lines.append(f"- {s['name']} \u2014 Father: {s['father_name']}, Class: {s['class']} {s['section']}, Phone: {s['phone'] or 'N/A'}")
    if len(matches) > 30:
        lines.append(f"\n...and {len(matches) - 30} more.")

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
        lines.append(f"- {s['name']} \u2014 Father: {s['father_name']}, Class: {s['class']} {s['section']}, Category: {s['category']}")
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


async def _answer_student_phone(school_id: str, msg: str) -> str:
    """Phone number lookup: 'phone number of Rahul in class 5 A'."""
    query = _extract_phone_query(msg)
    if not query:
        return "Please tell me the student name whose phone number you need."

    students = await _load_students(school_id)
    matches = [s for s in students if query in s["name"].lower()]

    # Optional class/section filter from the message
    class_filter = _extract_class_filter(msg)
    section_filter = _extract_section_filter(msg)
    if class_filter:
        filtered = [s for s in matches if class_filter in s["class"].lower()]
        if filtered:
            matches = filtered
    if section_filter:
        filtered = [s for s in matches if section_filter in s["section"].lower()]
        if filtered:
            matches = filtered

    if not matches:
        return f"No student found matching \"{query}\"."

    if len(matches) == 1:
        s = matches[0]
        phone = s['phone'] or 'Not available'
        return f"{s['name']} (Class {s['class']} {s['section']}) \u2014 Guardian phone: {phone}"

    lines = [f"Found {len(matches)} student(s) matching \"{query}\":\n"]
    for s in matches[:20]:
        phone = s['phone'] or 'N/A'
        lines.append(f"- {s['name']} \u2014 Class: {s['class']} {s['section']}, Phone: {phone}")
    if len(matches) > 20:
        lines.append(f"\n...and {len(matches) - 20} more. Try adding the class/section to narrow down.")

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
# Announcement
# ===================================================================

async def _answer_send_announcement(school_id: str, original_msg: str, user: Dict) -> str:
    """Extract title+body from the user message and create an announcement for all users."""
    extracted = await _llm_extract_json(
        original_msg,
        "Extract the announcement title and body/message from this admin request. "
        "Return JSON: {\"title\": \"...\", \"body\": \"...\"}. "
        "If the user just gave a message without a separate title, generate a short title from the message. "
        "Keep the body exactly as the user intended it.",
    )
    title = (extracted.get("title") or "").strip()
    body = (extracted.get("body") or "").strip()

    if not title and not body:
        return (
            "Please tell me the announcement you want to send. For example:\n"
            "\"Send announcement: Tomorrow is a holiday due to heavy rain.\"\n\n"
            "Or:\n\"Create announcement title: Holiday Notice, message: School will remain "
            "closed tomorrow due to weather.\""
        )

    if not title:
        title = body[:60] + ("..." if len(body) > 60 else "")
    if not body:
        body = title

    client = get_client()
    author = user.get("full_name") or "Admin"
    row = {
        "school_id": school_id,
        "title": title.strip(),
        "body": body.strip(),
        "audience": "all",
        "author": author,
    }
    inserted = await client.table("announcements").insert(row).execute()
    if not inserted.data:
        return "Sorry, I couldn't create the announcement. Please try again."

    # Notify all users
    try:
        from services.notification_service import notify_school
        await notify_school(school_id, f"New announcement: {title}", body[:280])
    except Exception:
        logger.warning("Failed to send notification for announcement")

    return (
        f"Announcement sent to all users!\n\n"
        f"Title: {title}\n"
        f"Message: {body}"
    )


# ===================================================================
# Calendar event
# ===================================================================

async def _answer_add_calendar_event(school_id: str, original_msg: str, user: Dict) -> str:
    """Parse event details from the message and add to the school calendar."""
    today_str = date.today().isoformat()
    extracted = await _llm_extract_json(
        original_msg,
        f"Extract calendar event details from this admin request. Today is {today_str}. "
        "Return JSON: {\"title\": \"...\", \"event_date\": \"YYYY-MM-DD\", "
        "\"end_date\": \"YYYY-MM-DD or null\", \"event_type\": \"holiday|special_day\"}. "
        "event_type must be exactly 'holiday' or 'special_day'. "
        "If user says holiday use 'holiday', for events/celebrations use 'special_day'. "
        "If the user doesn't mention a year, assume the current or next occurrence. "
        "The title should be a clean, proper name for the event.",
    )

    title = (extracted.get("title") or "").strip()
    if not title:
        return (
            "Please tell me the event details. For example:\n"
            "\"Add holiday on 15 August: Independence Day\"\n"
            "\"Add event on 25 December: Christmas celebration\"\n"
            "\"Mark holiday from 1 November to 5 November: Diwali break\""
        )

    event_date = (extracted.get("event_date") or "").strip() or today_str
    end_date = (extracted.get("end_date") or "").strip() or None
    if end_date == "null":
        end_date = None
    event_type = (extracted.get("event_type") or "holiday").strip()
    if event_type not in ("holiday", "special_day"):
        event_type = "holiday"

    client = get_client()
    created_by = user.get("full_name") or "Admin"
    payload = {
        "id": str(uuid.uuid4()),
        "school_id": school_id,
        "event_type": event_type,
        "title": title.strip(),
        "description": None,
        "event_date": event_date,
        "end_date": end_date or event_date,
        "created_by": created_by,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await client.table("school_calendar_events").insert(payload).execute()
    if not res.data:
        return "Sorry, I couldn't add the event to the calendar. Please try again."

    reply = f"Added to school calendar!\n\nType: {event_type.replace('_', ' ').title()}\nTitle: {title}\nDate: {event_date}"
    if end_date and end_date != event_date:
        reply += f" to {end_date}"
    return reply


# ===================================================================
# Fee summary
# ===================================================================

async def _answer_fee_summary(school_id: str) -> str:
    """Fetch fee dashboard stats and return a summary."""
    from services.fee_structure_service import school_fee_dashboard_stats
    stats = await school_fee_dashboard_stats(school_id)

    total_due = stats.get("total_due", 0)
    paid_month = stats.get("paid_this_month", 0)
    unpaid = stats.get("unpaid_students_this_month", 0)

    today = date.today()
    month_label = today.strftime("%B %Y")

    lines = [
        f"Fee summary for {month_label}:\n",
        f"- Total pending dues: Rs {total_due:,.0f}",
        f"- Collected this month: Rs {paid_month:,.0f}",
        f"- Students with unpaid fees this month: {unpaid}",
    ]
    return "\n".join(lines)


# ===================================================================
# Expense / income summary
# ===================================================================

async def _answer_expense_summary(school_id: str) -> str:
    """Fetch current month income/expense report."""
    today = date.today()
    month_label = today.strftime("%B %Y")

    client = get_client()
    # Fetch expense_transactions for this month
    from calendar import monthrange
    month_start = date(today.year, today.month, 1).isoformat()
    month_end = date(today.year, today.month, monthrange(today.year, today.month)[1]).isoformat()

    tx_res = await (
        client.table("expense_transactions")
        .select("amount,type,transaction_date")
        .eq("school_id", school_id)
        .gte("transaction_date", month_start)
        .lte("transaction_date", month_end)
        .execute()
    )

    income = 0.0
    expenses = 0.0
    for row in (tx_res.data or []):
        amt = float(row.get("amount") or 0)
        if row.get("type") == "income":
            income += amt
        else:
            expenses += amt

    # Also add fee payments as income
    pay_res = await (
        client.table("payments")
        .select("amount")
        .eq("school_id", school_id)
        .gte("paid_at", f"{month_start}T00:00:00")
        .lte("paid_at", f"{month_end}T23:59:59")
        .execute()
    )
    for row in (pay_res.data or []):
        income += float(row.get("amount") or 0)

    income = round(income, 2)
    expenses = round(expenses, 2)
    profit = round(income - expenses, 2)

    lines = [
        f"Financial summary for {month_label}:\n",
        f"- Total income: Rs {income:,.0f}",
        f"- Total expenses: Rs {expenses:,.0f}",
        f"- Net profit: Rs {profit:,.0f}",
    ]
    return "\n".join(lines)


# ===================================================================
# LLM extraction helper
# ===================================================================

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"


async def _llm_extract_json(user_msg: str, system_instruction: str) -> Dict[str, Any]:
    """Use Groq to extract structured JSON from a user message.

    Returns the parsed dict or {} on failure.
    """
    settings = get_settings()
    api_key = settings.groq_api_key
    model = settings.groq_model or "llama-3.1-8b-instant"
    if not api_key:
        logger.warning("No GROQ_API_KEY — falling back to regex extraction")
        return {}

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_instruction + "\nRespond ONLY with valid JSON, no markdown, no explanation."},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.0,
        "max_completion_tokens": 300,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                GROQ_CHAT_URL,
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
                json=payload,
            )
        if res.status_code >= 400:
            logger.warning("LLM extract failed: %s %s", res.status_code, res.text[:200])
            return {}

        data = res.json()
        text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = re.sub(r'^```\w*\n?', '', text)
            text = re.sub(r'\n?```$', '', text)
        return json.loads(text)
    except (json.JSONDecodeError, httpx.HTTPError, Exception) as exc:
        logger.warning("LLM extract error: %s", exc)
        return {}


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
        "named ",
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


def _extract_search_query(msg: str) -> Optional[str]:
    """Extract name from generic search queries."""
    patterns = [
        "search student ", "search for student ", "find student ",
        "look up student ", "lookup student ", "search students ",
    ]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            # Remove trailing class/section hints
            for stop in [" in class", " of class", " from class"]:
                si = rest.find(stop)
                if si != -1:
                    rest = rest[:si]
            words = rest.split()[:3]
            name = " ".join(words).strip("?.,! ")
            if name:
                return name.lower()
    return None


def _extract_phone_query(msg: str) -> Optional[str]:
    """Extract student name from phone lookup queries."""
    patterns = [
        "phone number of ", "mobile number of ", "contact number of ",
        "phone of ", "mobile of ", "contact of ",
        "phone no of ", "guardian number of ", "parent number of ",
        "parent contact of ", "parent mobile of ",
    ]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            # Remove class/section hints from the end
            for stop in [" in class", " of class", " from class", " class "]:
                si = rest.find(stop)
                if si != -1:
                    rest = rest[:si]
            words = rest.split()[:3]
            name = " ".join(words).strip("?.,! ")
            if name:
                return name.lower()
    return None


def _extract_class_filter(msg: str) -> Optional[str]:
    """Extract class name/number from message like 'in class 5' or 'class 10'."""
    patterns = ["in class ", "of class ", "from class ", "class "]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            word = rest.split()[0].strip("?.,! ") if rest.split() else ""
            if word:
                return word.lower()
    return None


def _extract_section_filter(msg: str) -> Optional[str]:
    """Extract section from message like 'section A' or 'section b'."""
    patterns = ["section "]
    for pat in patterns:
        idx = msg.find(pat)
        if idx != -1:
            rest = msg[idx + len(pat):].strip()
            word = rest.split()[0].strip("?.,! ") if rest.split() else ""
            if word:
                return word.lower()
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


def _extract_announcement_content(msg: str) -> tuple:
    """Extract title and body from announcement message.

    Supports formats like:
    - "send announcement: <message>"
    - "create announcement title: X, message: Y"
    - "send this announcement <message>"
    """
    text = msg.strip()

    # Try "title: X, message: Y" / "title: X, body: Y"
    title_match = re.search(r'title\s*:\s*(.+?)(?:,\s*(?:message|body)\s*:\s*(.+))', text, re.IGNORECASE)
    if title_match:
        return title_match.group(1).strip(), (title_match.group(2) or "").strip()

    # Try after colon: "send announcement: message text here"
    for prefix in [
        "send announcement", "create announcement", "make announcement",
        "send this announcement", "send notice", "broadcast message",
        "announce to all", "announcement to all",
    ]:
        idx = text.lower().find(prefix)
        if idx != -1:
            rest = text[idx + len(prefix):].strip()
            # Remove leading colon, dash, or "that"
            rest = re.sub(r'^[\s:;\-]+', '', rest)
            rest = re.sub(r'^that\s+', '', rest, flags=re.IGNORECASE)
            if rest:
                return "", rest.strip()

    return "", ""


_MONTH_MAP = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "october": 10, "oct": 10,
    "november": 11, "nov": 11, "december": 12, "dec": 12,
}


def _parse_natural_date(text: str) -> Optional[str]:
    """Parse dates like '15 August', '25 Dec 2025', '2025-08-15'."""
    text = text.strip()

    # ISO format
    iso = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
    if iso:
        return text[:10]

    # "15 August" or "15 August 2025"
    m = re.match(r'(\d{1,2})\s+(\w+)(?:\s+(\d{4}))?', text)
    if m:
        day = int(m.group(1))
        month_name = m.group(2).lower()
        year = int(m.group(3)) if m.group(3) else date.today().year
        month_num = _MONTH_MAP.get(month_name)
        if month_num and 1 <= day <= 31:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass

    # "August 15" or "Aug 15, 2025"
    m = re.match(r'(\w+)\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?', text)
    if m:
        month_name = m.group(1).lower()
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else date.today().year
        month_num = _MONTH_MAP.get(month_name)
        if month_num and 1 <= day <= 31:
            try:
                return date(year, month_num, day).isoformat()
            except ValueError:
                pass

    return None


def _extract_calendar_event(msg: str) -> Dict[str, Any]:
    """Extract event type, title, date, end_date from natural language."""
    result: Dict[str, Any] = {"title": "", "date": None, "end_date": None, "type": "holiday"}

    text = msg.strip()

    # Determine event type
    lower = text.lower()
    if "special day" in lower or "special event" in lower or "celebration" in lower:
        result["type"] = "special_day"
    elif "holiday" in lower:
        result["type"] = "holiday"
    elif "event" in lower:
        result["type"] = "special_day"

    # Try "from DATE to DATE" pattern
    range_match = re.search(r'from\s+(.+?)\s+to\s+(.+?)(?:\s*[:\-]\s*(.+))?$', text, re.IGNORECASE)
    if range_match:
        d1 = _parse_natural_date(range_match.group(1))
        d2 = _parse_natural_date(range_match.group(2))
        title_part = (range_match.group(3) or "").strip()
        if d1:
            result["date"] = d1
            result["end_date"] = d2 or d1
            if title_part:
                result["title"] = title_part
            return result

    # Try "on DATE: title" or "on DATE title"
    on_match = re.search(r'on\s+(.+?)(?:\s*[:\-]\s*(.+))?$', text, re.IGNORECASE)
    if on_match:
        date_part = on_match.group(1).strip()
        title_part = (on_match.group(2) or "").strip()
        # The date part may also contain the title after the date
        parsed = _parse_natural_date(date_part)
        if parsed:
            result["date"] = parsed
            if title_part:
                result["title"] = title_part
            return result
        # Try splitting: "15 August Independence Day"
        words = date_part.split()
        for i in range(min(3, len(words)), 0, -1):
            candidate = " ".join(words[:i])
            parsed = _parse_natural_date(candidate)
            if parsed:
                result["date"] = parsed
                remaining = " ".join(words[i:]).strip(":- ")
                result["title"] = (remaining + " " + title_part).strip()
                return result

    # Fallback: remove the command prefix and try to find a date anywhere
    for prefix in ["add holiday", "add event", "create holiday", "create event",
                    "mark holiday", "add special day", "add to calendar", "calendar event"]:
        idx = lower.find(prefix)
        if idx != -1:
            rest = text[idx + len(prefix):].strip()
            rest = re.sub(r'^[\s:;\-]+', '', rest)
            # Try to find date in the rest
            date_match = re.search(r'(\d{1,2}\s+\w+(?:\s+\d{4})?)', rest)
            if date_match:
                parsed = _parse_natural_date(date_match.group(1))
                if parsed:
                    result["date"] = parsed
                    title = rest.replace(date_match.group(1), "").strip(":- ,")
                    result["title"] = title
                    return result
            # No date found, treat rest as title
            if rest:
                result["title"] = rest
            return result

    return result
