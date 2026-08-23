"""School Feed — posts, media, likes, comments."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import HTTPException, UploadFile, status

from database import get_client
from schemas.feed import (
    FeedCommentOut,
    FeedLikeOut,
    FeedMediaOut,
    FeedPostCreateIn,
    FeedPostOut,
)
from services import feed_media_service

_ADMIN_ROLES = {"school_admin", "principal", "vice_principal", "super_admin"}

_POST_COLUMNS = "id,school_id,author_id,author_name,author_role,caption,created_at"
_MEDIA_COLUMNS = "id,post_id,file_url,file_name,content_type,position"
_COMMENT_COLUMNS = "id,post_id,user_id,author_name,text,created_at"


async def upload_media(school_id: str, file: UploadFile) -> dict:
    return await feed_media_service.save_feed_media(school_id, file)


async def _hydrate_posts(school_id: str, rows: List[dict], viewer_id: str) -> List[FeedPostOut]:
    if not rows:
        return []
    post_ids = [row["id"] for row in rows]
    client = get_client()

    media_res = (
        await client.table("feed_post_media")
        .select(_MEDIA_COLUMNS)
        .in_("post_id", post_ids)
        .order("position")
        .execute()
    )
    media_by_post: Dict[str, List[dict]] = defaultdict(list)
    for row in media_res.data or []:
        media_by_post[row["post_id"]].append(row)

    likes_res = (
        await client.table("feed_likes")
        .select("post_id,user_id")
        .in_("post_id", post_ids)
        .execute()
    )
    like_counts: Dict[str, int] = defaultdict(int)
    liked_by_me: set[str] = set()
    for row in likes_res.data or []:
        like_counts[row["post_id"]] += 1
        if row.get("user_id") == viewer_id:
            liked_by_me.add(row["post_id"])

    comments_res = (
        await client.table("feed_comments")
        .select("post_id")
        .in_("post_id", post_ids)
        .execute()
    )
    comment_counts: Dict[str, int] = defaultdict(int)
    for row in comments_res.data or []:
        comment_counts[row["post_id"]] += 1

    out: List[FeedPostOut] = []
    for row in rows:
        pid = row["id"]
        out.append(
            FeedPostOut(
                **row,
                media=[FeedMediaOut(**m) for m in media_by_post.get(pid, [])],
                like_count=like_counts.get(pid, 0),
                comment_count=comment_counts.get(pid, 0),
                liked_by_me=pid in liked_by_me,
            )
        )
    return out


async def list_posts(
    school_id: str,
    viewer_id: str,
    limit: int = 20,
    before_id: Optional[str] = None,
) -> List[FeedPostOut]:
    client = get_client()
    query = client.table("feed_posts").select(_POST_COLUMNS).eq("school_id", school_id)

    if before_id:
        anchor = (
            await client.table("feed_posts")
            .select("created_at")
            .eq("school_id", school_id)
            .eq("id", before_id)
            .limit(1)
            .execute()
        )
        if anchor.data:
            query = query.lt("created_at", anchor.data[0]["created_at"])

    res = await query.order("created_at", desc=True).limit(limit).execute()
    return await _hydrate_posts(school_id, res.data or [], viewer_id)


async def get_post(school_id: str, post_id: str, viewer_id: str) -> FeedPostOut:
    client = get_client()
    res = (
        await client.table("feed_posts")
        .select(_POST_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", post_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    hydrated = await _hydrate_posts(school_id, res.data, viewer_id)
    return hydrated[0]


async def create_post(school_id: str, user: dict, body: FeedPostCreateIn) -> FeedPostOut:
    caption = (body.caption or "").strip()
    media_urls = [u for u in (body.media_urls or []) if u]
    if not caption and not media_urls:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Add a caption or at least one photo to post."
        )

    client = get_client()
    inserted = (
        await client.table("feed_posts")
        .insert(
            {
                "school_id": school_id,
                "author_id": user["id"],
                "author_name": user.get("full_name") or user.get("email") or "User",
                "author_role": user.get("role") or "",
                "caption": caption,
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create post")
    post_row = inserted.data[0]
    post_id = post_row["id"]

    if media_urls:
        media_rows = []
        for index, url in enumerate(media_urls):
            filename = url.rsplit("/", 1)[-1]
            ext = f".{filename.rsplit('.', 1)[-1].lower()}" if "." in filename else ""
            media_rows.append(
                {
                    "post_id": post_id,
                    "school_id": school_id,
                    "file_url": url,
                    "file_name": filename,
                    "content_type": feed_media_service.MIME_BY_EXT.get(ext, "image/jpeg"),
                    "position": index,
                }
            )
        await client.table("feed_post_media").insert(media_rows).execute()

    return await get_post(school_id, post_id, user["id"])


async def delete_post(school_id: str, post_id: str, user: dict) -> None:
    client = get_client()
    res = (
        await client.table("feed_posts")
        .select("id,author_id")
        .eq("school_id", school_id)
        .eq("id", post_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")
    post = res.data[0]
    if post["author_id"] != user["id"] and user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't delete this post")

    media_res = (
        await client.table("feed_post_media")
        .select("file_url")
        .eq("post_id", post_id)
        .execute()
    )
    for row in media_res.data or []:
        filename = (row.get("file_url") or "").rsplit("/", 1)[-1]
        if filename:
            feed_media_service.delete_feed_file(school_id, filename)

    await client.table("feed_posts").delete().eq("school_id", school_id).eq(
        "id", post_id
    ).execute()


async def toggle_like(school_id: str, post_id: str, user_id: str) -> FeedLikeOut:
    client = get_client()
    post_res = (
        await client.table("feed_posts")
        .select("id")
        .eq("school_id", school_id)
        .eq("id", post_id)
        .limit(1)
        .execute()
    )
    if not post_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")

    existing = (
        await client.table("feed_likes")
        .select("id")
        .eq("post_id", post_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        await client.table("feed_likes").delete().eq(
            "id", existing.data[0]["id"]
        ).execute()
        liked = False
    else:
        await client.table("feed_likes").insert(
            {"post_id": post_id, "user_id": user_id}
        ).execute()
        liked = True

    count_res = (
        await client.table("feed_likes").select("id").eq("post_id", post_id).execute()
    )
    return FeedLikeOut(liked=liked, like_count=len(count_res.data or []))


async def list_comments(school_id: str, post_id: str) -> List[FeedCommentOut]:
    client = get_client()
    post_res = (
        await client.table("feed_posts")
        .select("id")
        .eq("school_id", school_id)
        .eq("id", post_id)
        .limit(1)
        .execute()
    )
    if not post_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")

    res = (
        await client.table("feed_comments")
        .select(_COMMENT_COLUMNS)
        .eq("post_id", post_id)
        .order("created_at")
        .limit(500)
        .execute()
    )
    return [FeedCommentOut(**row) for row in (res.data or [])]


async def add_comment(school_id: str, post_id: str, user: dict, text: str) -> FeedCommentOut:
    client = get_client()
    post_res = (
        await client.table("feed_posts")
        .select("id")
        .eq("school_id", school_id)
        .eq("id", post_id)
        .limit(1)
        .execute()
    )
    if not post_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Post not found")

    inserted = (
        await client.table("feed_comments")
        .insert(
            {
                "post_id": post_id,
                "school_id": school_id,
                "user_id": user["id"],
                "author_name": user.get("full_name") or user.get("email") or "User",
                "text": text.strip(),
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to add comment")
    return FeedCommentOut(**inserted.data[0])


async def delete_comment(school_id: str, comment_id: str, user: dict) -> None:
    client = get_client()
    res = (
        await client.table("feed_comments")
        .select("id,user_id")
        .eq("school_id", school_id)
        .eq("id", comment_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    comment = res.data[0]
    if comment["user_id"] != user["id"] and user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't delete this comment")
    await client.table("feed_comments").delete().eq("id", comment_id).execute()
