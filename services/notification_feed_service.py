"""Aggregate notifications from multiple sources into a unified feed.

Sources:
- announcements (for-me endpoint logic)
- forms (published, not yet responded)
- quizzes (published, not yet attempted)
- appointments (upcoming PTM/meetings)
- fees (pending dues)
- push notifications table
"""
from datetime import datetime, timezone
from typing import List

from database import get_client
from schemas.content import NotificationFeedItem


async def _student_class_section(school_id: str, user_id: str) -> tuple:
    """Return (class_id, section_id) for a student."""
    client = get_client()
    res = (
        await client.table("students")
        .select("class_id,section_id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None, None
    return res.data[0].get("class_id"), res.data[0].get("section_id")


async def _announcement_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Recent announcements visible to this user."""
    client = get_client()
    res = (
        await client.table("announcements")
        .select("id,title,body,audience,author,created_at,recipient_user_id,recipient_type,audience_targets")
        .eq("school_id", school_id)
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    items: List[NotificationFeedItem] = []
    role = user.get("role") or ""
    for row in res.data or []:
        audience = row.get("audience") or "all"
        # Filter by audience
        if audience in ("all", "school"):
            pass
        elif audience == "teachers" and role != "teacher":
            continue
        elif audience == "students" and role != "student":
            continue
        elif audience == "specific":
            if row.get("recipient_user_id") != user["id"]:
                continue
        elif audience == "class":
            if role != "student":
                continue
            targets = row.get("audience_targets") or {}
            class_ids = targets.get("class_ids") or []
            section_ids = targets.get("section_ids") or []
            if class_ids:
                stu_class, stu_section = await _student_class_section(school_id, user["id"])
                if stu_class not in class_ids:
                    continue
                if section_ids and stu_section not in section_ids:
                    continue
        created = row.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        items.append(NotificationFeedItem(
            id=f"ann_{row['id']}",
            type="announcement",
            title=row.get("title") or "",
            body=row.get("body") or "",
            icon="megaphone",
            route="/(app)/announcements",
            created_at=created or datetime.now(timezone.utc),
            metadata={"author": row.get("author") or ""},
        ))
    return items


async def _forms_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Published forms not yet responded to."""
    if user.get("role") != "student":
        return []
    client = get_client()
    res = (
        await client.table("forms")
        .select("id,title,description,published_at,created_at")
        .eq("school_id", school_id)
        .eq("status", "published")
        .order("published_at", desc=True)
        .limit(10)
        .execute()
    )
    if not res.data:
        return []
    # Check which forms the student has already responded to
    form_ids = [r["id"] for r in res.data]
    resp_res = (
        await client.table("form_responses")
        .select("form_id")
        .eq("school_id", school_id)
        .eq("user_id", user["id"])
        .in_("form_id", form_ids)
        .execute()
    )
    responded = {r["form_id"] for r in (resp_res.data or [])}
    items: List[NotificationFeedItem] = []
    for row in res.data:
        if row["id"] in responded:
            continue
        created = row.get("published_at") or row.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        items.append(NotificationFeedItem(
            id=f"form_{row['id']}",
            type="form",
            title=f"New form: {row.get('title') or ''}",
            body=row.get("description") or "",
            icon="file-text",
            route="/(app)/create-form",
            created_at=created or datetime.now(timezone.utc),
        ))
    return items


async def _quizzes_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Published quizzes not yet attempted."""
    if user.get("role") != "student":
        return []
    class_id, section_id = await _student_class_section(school_id, user["id"])
    if not class_id:
        return []
    client = get_client()
    query = (
        client.table("quizzes")
        .select("id,title,subject,start_at,end_at,published_at,created_at")
        .eq("school_id", school_id)
        .eq("status", "published")
    )
    query = query.or_(f"class_id.eq.{class_id},visibility.eq.all")
    res = await query.order("published_at", desc=True).limit(10).execute()
    if not res.data:
        return []
    quiz_ids = [r["id"] for r in res.data]
    att_res = (
        await client.table("quiz_attempts")
        .select("quiz_id")
        .eq("school_id", school_id)
        .eq("user_id", user["id"])
        .in_("quiz_id", quiz_ids)
        .execute()
    )
    attempted = {r["quiz_id"] for r in (att_res.data or [])}
    items: List[NotificationFeedItem] = []
    for row in res.data:
        if row["id"] in attempted:
            continue
        created = row.get("published_at") or row.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        meta = {}
        if row.get("start_at"):
            meta["start_at"] = row["start_at"]
        if row.get("end_at"):
            meta["end_at"] = row["end_at"]
        items.append(NotificationFeedItem(
            id=f"quiz_{row['id']}",
            type="quiz",
            title=f"New quiz: {row.get('title') or ''}",
            body=row.get("subject") or "",
            icon="help-circle",
            route="/(app)/quiz",
            created_at=created or datetime.now(timezone.utc),
            metadata=meta or None,
        ))
    return items


async def _appointments_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Upcoming appointments/PTM for the user."""
    client = get_client()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    query = (
        client.table("appointments")
        .select("id,title,appointment_date,appointment_time,description,status,created_at")
        .eq("school_id", school_id)
        .gte("appointment_date", today)
        .order("appointment_date", asc=True)
        .limit(10)
    )
    # Non-admins only see their own
    role = user.get("role") or ""
    if role not in ("school_admin", "principal", "vice_principal", "super_admin", "office_staff"):
        query = query.eq("user_id", user["id"])
    res = await query.execute()
    items: List[NotificationFeedItem] = []
    for row in res.data or []:
        created = row.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        meta = {}
        if row.get("appointment_date"):
            meta["appointment_date"] = row["appointment_date"]
        if row.get("appointment_time"):
            meta["appointment_time"] = row["appointment_time"]
        items.append(NotificationFeedItem(
            id=f"apt_{row['id']}",
            type="appointment",
            title=f"PTM: {row.get('title') or ''}",
            body=row.get("description") or "",
            icon="calendar",
            route="/(app)/appointments",
            created_at=created or datetime.now(timezone.utc),
            metadata=meta or None,
        ))
    return items


async def _fees_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Pending fees with upcoming or overdue due dates."""
    if user.get("role") != "student":
        return []
    client = get_client()
    res = (
        await client.table("fees")
        .select("id,title,amount,due_date,status,created_at")
        .eq("school_id", school_id)
        .eq("student_email", user.get("email") or "")
        .eq("status", "pending")
        .order("due_date", asc=True)
        .limit(10)
        .execute()
    )
    items: List[NotificationFeedItem] = []
    for row in res.data or []:
        created = row.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        meta = {}
        if row.get("due_date"):
            meta["due_date"] = row["due_date"]
        if row.get("amount"):
            meta["amount"] = row["amount"]
        items.append(NotificationFeedItem(
            id=f"fee_{row['id']}",
            type="fee",
            title=f"Fees due: {row.get('title') or ''}",
            body=f"Amount: {row.get('amount') or 0}",
            icon="credit-card",
            route="/(app)/fees",
            created_at=created or datetime.now(timezone.utc),
            metadata=meta or None,
        ))
    return items


async def _push_notifications_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Existing push notifications from the notifications table."""
    client = get_client()
    res = (
        await client.table("notifications")
        .select("id,title,body,is_read,created_at")
        .eq("school_id", school_id)
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    items: List[NotificationFeedItem] = []
    for row in res.data or []:
        created = row.get("created_at")
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        items.append(NotificationFeedItem(
            id=f"notif_{row['id']}",
            type="notification",
            title=row.get("title") or "",
            body=row.get("body") or "",
            icon="bell",
            is_read=row.get("is_read", False),
            created_at=created or datetime.now(timezone.utc),
        ))
    return items


async def get_notification_feed(school_id: str, user: dict) -> List[NotificationFeedItem]:
    """Aggregate all notification sources into a single feed, sorted by date."""
    # Fetch all sources in parallel
    results = await _gather(
        _announcement_feed(school_id, user),
        _forms_feed(school_id, user),
        _quizzes_feed(school_id, user),
        _appointments_feed(school_id, user),
        _fees_feed(school_id, user),
        _push_notifications_feed(school_id, user),
    )
    all_items: List[NotificationFeedItem] = []
    for batch in results:
        all_items.extend(batch)
    # Sort by created_at descending
    all_items.sort(key=lambda x: x.created_at, reverse=True)
    return all_items[:100]  # cap at 100


async def _gather(*coros):
    """Simple parallel gather without importing asyncio at top level."""
    import asyncio
    return await asyncio.gather(*coros, return_exceptions=False)
