"""Chat message helpers with rolling 1-year retention per school."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from database import get_client
from services.chat_media_service import delete_chat_file, filename_from_media_url

MESSAGE_RETENTION_DAYS = 365


def retention_start(today: date | None = None) -> date:
    anchor = today or date.today()
    return anchor - timedelta(days=MESSAGE_RETENTION_DAYS - 1)


def retention_cutoff_iso(today: date | None = None) -> str:
    return datetime.combine(
        retention_start(today or date.today()),
        time.min,
        tzinfo=timezone.utc,
    ).isoformat()


async def purge_expired_messages(school_id: str, today: date | None = None) -> None:
    """Delete messages older than the 1-year window and drop attached media files."""
    cutoff = retention_cutoff_iso(today)
    client = get_client()

    expired = (
        await client.table("messages")
        .select("id,media_url")
        .eq("school_id", school_id)
        .lt("created_at", cutoff)
        .limit(2000)
        .execute()
    )
    for row in expired.data or []:
        media_url = row.get("media_url")
        if media_url:
            delete_chat_file(school_id, filename_from_media_url(media_url))

    await (
        client.table("messages")
        .delete()
        .eq("school_id", school_id)
        .lt("created_at", cutoff)
        .execute()
    )
