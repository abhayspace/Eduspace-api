"""In-app notification + device-token storage.

Notifications are persisted in PostgreSQL; device tokens are stored so a real
push provider can be wired in later without changing call sites.
"""
import logging
from typing import List, Optional

import httpx

from database import get_client

logger = logging.getLogger("eduspace.notifications")

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def _send_expo_push(user_ids: List[str], title: str, body: str) -> None:
    """Deliver a push notification via the Expo push service. Best-effort.

    Only Expo push tokens (ExponentPushToken[...]) are sent — legacy raw
    FCM/APNs device tokens are skipped.
    """
    try:
        client = get_client()
        res = (
            await client.table("device_tokens")
            .select("device_token")
            .in_("user_id", user_ids)
            .execute()
        )
        tokens = [
            row["device_token"]
            for row in (res.data or [])
            if str(row.get("device_token") or "").startswith("ExponentPushToken")
        ]
        if not tokens:
            return
        messages = [
            {
                "to": token,
                "sound": "default",
                "title": title,
                "body": body[:280],
            }
            for token in tokens
        ]
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.post(
                EXPO_PUSH_URL,
                json=messages,
                headers={"Accept": "application/json"},
            )
            if resp.status_code >= 400:
                logger.warning("expo push send failed: %s %s", resp.status_code, resp.text[:200])
    except Exception as exc:  # noqa: BLE001 - push delivery must never break callers
        logger.warning("_send_expo_push failed (non-blocking): %s", exc)


async def register_device(user_id: str, platform: str, device_token: str) -> None:
    client = get_client()
    try:
        await (
            client.table("device_tokens")
            .upsert(
                {"user_id": user_id, "platform": platform, "device_token": device_token},
                on_conflict="user_id,device_token",
            )
            .execute()
        )
    except Exception as exc:  # noqa: BLE001 - registration must never break auth
        logger.warning("register_device failed (non-blocking): %s", exc)


async def _active_school_user_ids(school_id: str, exclude_user_id: Optional[str]) -> List[str]:
    client = get_client()
    res = (
        await client.table("users")
        .select("id")
        .eq("school_id", school_id)
        .eq("is_active", True)
        .execute()
    )
    return [row["id"] for row in (res.data or []) if row["id"] != exclude_user_id]


async def _insert_notifications(school_id: str, user_ids: List[str], title: str, body: str) -> None:
    """Persist one notification row per user. Internal helper."""
    if not user_ids:
        return
    client = get_client()
    rows = [
        {
            "school_id": school_id,
            "user_id": uid,
            "title": title,
            "body": body[:280],
        }
        for uid in user_ids
    ]
    await client.table("notifications").insert(rows).execute()


async def _parent_user_ids_for_students(school_id: str, student_ids: List[str]) -> List[str]:
    """Parent user accounts linked to the given student profile ids."""
    if not student_ids:
        return []
    client = get_client()
    res = (
        await client.table("parents")
        .select("user_id")
        .eq("school_id", school_id)
        .in_("student_id", student_ids)
        .execute()
    )
    return [row["user_id"] for row in (res.data or []) if row.get("user_id")]


async def _student_user_ids_for_class(
    school_id: str,
    class_name: Optional[str],
    section_name: Optional[str],
) -> tuple[List[str], List[str]]:
    """Return (student_user_ids, student_profile_ids) for a class/section name pair."""
    client = get_client()
    cls_query = (
        client.table("classes")
        .select("id,sections(id,name)")
        .eq("school_id", school_id)
    )
    cls_res = await cls_query.execute()
    class_ids: List[str] = []
    section_ids: List[str] = []
    for row in cls_res.data or []:
        if class_name and str(row.get("name") or "").strip().lower() != class_name.strip().lower():
            continue
        class_ids.append(row["id"])
        for sec in row.get("sections") or []:
            if section_name and str(sec.get("name") or "").strip().lower() != section_name.strip().lower():
                continue
            section_ids.append(sec["id"])
    if not class_ids:
        return [], []
    query = (
        client.table("students")
        .select("id,user_id,section_id")
        .eq("school_id", school_id)
        .in_("class_id", class_ids)
    )
    res = await query.execute()
    profiles = res.data or []
    if section_name:
        profiles = [p for p in profiles if p.get("section_id") in section_ids]
    user_ids = [p["user_id"] for p in profiles if p.get("user_id")]
    profile_ids = [p["id"] for p in profiles if p.get("id")]
    return user_ids, profile_ids


async def notify_users(
    school_id: str,
    user_ids: List[str],
    title: str,
    body: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Notify a specific set of users (in-app row + device push). Best-effort."""
    try:
        targets = [uid for uid in dict.fromkeys(user_ids) if uid != exclude_user_id]
        if not targets:
            return
        await _insert_notifications(school_id, targets, title, body)
        await _send_expo_push(targets, title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_users failed (non-blocking): %s", exc)


async def notify_school_roles(
    school_id: str,
    roles: List[str],
    title: str,
    body: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Fan out to every active school user whose role is in `roles`. Best-effort."""
    try:
        client = get_client()
        res = (
            await client.table("users")
            .select("id")
            .eq("school_id", school_id)
            .eq("is_active", True)
            .in_("role", roles)
            .execute()
        )
        user_ids = [row["id"] for row in (res.data or []) if row["id"] != exclude_user_id]
        await notify_users(school_id, user_ids, title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_school_roles failed (non-blocking): %s", exc)


async def notify_student_and_parents(
    school_id: str,
    student_profile_id: Optional[str],
    student_user_id: Optional[str],
    title: str,
    body: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Notify one student (by user id) plus all parent accounts linked to them."""
    try:
        targets = [student_user_id] if student_user_id else []
        if student_profile_id:
            targets += await _parent_user_ids_for_students(school_id, [student_profile_id])
        await notify_users(school_id, targets, title, body, exclude_user_id=exclude_user_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_student_and_parents failed (non-blocking): %s", exc)


async def notify_class_users(
    school_id: str,
    class_name: Optional[str],
    section_name: Optional[str],
    title: str,
    body: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Notify students of a class/section plus their linked parents. Best-effort."""
    try:
        student_user_ids, profile_ids = await _student_user_ids_for_class(
            school_id, class_name, section_name
        )
        parent_user_ids = await _parent_user_ids_for_students(school_id, profile_ids)
        await notify_users(
            school_id,
            student_user_ids + parent_user_ids,
            title,
            body,
            exclude_user_id=exclude_user_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_class_users failed (non-blocking): %s", exc)


async def notify_user(
    school_id: str,
    user_id: str,
    title: str,
    body: str,
) -> None:
    """Notify a single user. Best-effort."""
    try:
        client = get_client()
        await (
            client.table("notifications")
            .insert(
                {
                    "school_id": school_id,
                    "user_id": user_id,
                    "title": title,
                    "body": body[:280],
                }
            )
            .execute()
        )
        await _send_expo_push([user_id], title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_user failed (non-blocking): %s", exc)


async def notify_school(
    school_id: str,
    title: str,
    body: str,
    *,
    exclude_user_id: Optional[str] = None,
) -> None:
    """Fan out a notification to every active user in a school. Best-effort."""
    try:
        user_ids = await _active_school_user_ids(school_id, exclude_user_id)
        if not user_ids:
            return
        rows = [
            {
                "school_id": school_id,
                "user_id": uid,
                "title": title,
                "body": body[:280],
            }
            for uid in user_ids
        ]
        client = get_client()
        await client.table("notifications").insert(rows).execute()
        await _send_expo_push(user_ids, title, body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_school failed (non-blocking): %s", exc)
