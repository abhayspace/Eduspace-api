"""Chat message helpers with rolling 1-year retention per school."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Optional

from database import get_client
from services.chat_media_service import (
    STORAGE_DIR,
    VIDEO_EXTENSIONS,
    delete_chat_file,
    filename_from_media_url,
)

MESSAGE_RETENTION_DAYS = 365
VIDEO_FILE_TTL_DAYS = 7  # Video files deleted from server after 7 days; users keep local copies


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


async def purge_old_video_files(school_id: str, today: date | None = None) -> int:
    """Delete video files older than VIDEO_FILE_TTL_DAYS from server storage.

    Message metadata (with media_url) is preserved so users who have the video
    cached locally can re-upload it via the /messages/reupload endpoint.
    Returns the number of files deleted.
    """
    cutoff = datetime.combine(
        (today or date.today()) - timedelta(days=VIDEO_FILE_TTL_DAYS),
        time.min,
        tzinfo=timezone.utc,
    ).isoformat()

    client = get_client()
    old_videos = (
        await client.table("messages")
        .select("id,media_url,created_at")
        .eq("school_id", school_id)
        .eq("media_type", "video")
        .lt("created_at", cutoff)
        .limit(500)
        .execute()
    )

    deleted = 0
    for row in old_videos.data or []:
        media_url = row.get("media_url")
        if not media_url:
            continue
        filename = filename_from_media_url(media_url)
        safe = Path(filename).name
        if safe != filename or ".." in filename:
            continue
        path = STORAGE_DIR / school_id / safe
        if path.is_file():
            path.unlink(missing_ok=True)
            deleted += 1

    return deleted
