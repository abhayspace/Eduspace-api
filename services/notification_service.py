"""In-app notification + device-token storage.

Notifications are persisted in PostgreSQL; device tokens are stored so a real
push provider can be wired in later without changing call sites.
"""
import logging
from typing import List, Optional

from database import get_client

logger = logging.getLogger("eduspace.notifications")


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
    except Exception as exc:  # noqa: BLE001
        logger.warning("notify_school failed (non-blocking): %s", exc)
