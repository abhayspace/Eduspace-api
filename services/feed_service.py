"""School Feed — posts, media, likes, comments."""
from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Optional

from fastapi import HTTPException, UploadFile, status

from database import get_client
from schemas.feed import (
    FeedCommentOut,
    FeedCommentUpdateIn,
    FeedLikeOut,
    FeedMediaOut,
    FeedPostCreateIn,
    FeedPostOut,
    FeedPostUpdateIn,
    FeedRestrictionOut,
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
    author_ids = list({row["author_id"] for row in rows if row.get("author_id")})
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

    # Author profile info (gender + user_code) so the app can render the same
    # avatar it uses in Messages. Teachers table is a fallback for gender.
    author_gender: Dict[str, Optional[str]] = {}
    author_user_code: Dict[str, str] = {}
    if author_ids:
        users_res = (
            await client.table("users")
            .select("id,gender,user_code")
            .in_("id", author_ids)
            .execute()
        )
        missing_gender: List[str] = []
        for row in users_res.data or []:
            uid = row["id"]
            author_user_code[uid] = row.get("user_code") or ""
            if row.get("gender"):
                author_gender[uid] = row["gender"]
            else:
                missing_gender.append(uid)
        if missing_gender:
            teacher_res = (
                await client.table("teachers")
                .select("user_id,gender")
                .in_("user_id", missing_gender)
                .execute()
            )
            for row in teacher_res.data or []:
                if row.get("gender"):
                    author_gender[row["user_id"]] = row["gender"]

    # Restriction status per author (admin can stop a person from posting).
    restricted_authors: set[str] = set()
    if author_ids:
        restr_res = (
            await client.table("feed_posting_restrictions")
            .select("user_id")
            .eq("school_id", school_id)
            .in_("user_id", author_ids)
            .execute()
        )
        for row in restr_res.data or []:
            restricted_authors.add(row["user_id"])

    out: List[FeedPostOut] = []
    for row in rows:
        pid = row["id"]
        aid = row.get("author_id")
        out.append(
            FeedPostOut(
                **row,
                author_gender=author_gender.get(aid),
                author_user_code=author_user_code.get(aid, ""),
                author_restricted=aid in restricted_authors,
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


async def _is_restricted(school_id: str, user_id: str) -> bool:
    client = get_client()
    res = (
        await client.table("feed_posting_restrictions")
        .select("id")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    return bool(res.data)


async def create_post(school_id: str, user: dict, body: FeedPostCreateIn) -> FeedPostOut:
    caption = (body.caption or "").strip()
    media_urls = [u for u in (body.media_urls or []) if u]
    if not caption and not media_urls:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Add a caption or at least one photo to post."
        )

    if await _is_restricted(school_id, user["id"]):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "You are restricted from posting to the School Feed. Contact your school admin.",
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


async def update_post(school_id: str, post_id: str, user: dict, body: FeedPostUpdateIn) -> FeedPostOut:
    """Edit a post's caption. Author or admin can edit."""
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
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this post")

    caption = (body.caption or "").strip()
    await (
        client.table("feed_posts")
        .update({"caption": caption})
        .eq("school_id", school_id)
        .eq("id", post_id)
        .execute()
    )
    return await get_post(school_id, post_id, user["id"])


async def restrict_author(school_id: str, user_id: str, admin: dict, reason: str) -> FeedRestrictionOut:
    """Admin stops a person from creating new feed posts."""
    if user_id == admin["id"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You can't restrict yourself")
    client = get_client()
    target_res = (
        await client.table("users")
        .select("id,role")
        .eq("school_id", school_id)
        .eq("id", user_id)
        .limit(1)
        .execute()
    )
    if not target_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    if target_res.data[0].get("role") in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Admins cannot be restricted")

    existing = (
        await client.table("feed_posting_restrictions")
        .select("id,user_id,restricted_by,reason,created_at")
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if existing.data:
        row = existing.data[0]
        return FeedRestrictionOut(
            user_id=row["user_id"],
            restricted_by=row.get("restricted_by"),
            reason=row.get("reason") or "",
            created_at=row.get("created_at"),
        )

    inserted = (
        await client.table("feed_posting_restrictions")
        .insert(
            {
                "school_id": school_id,
                "user_id": user_id,
                "restricted_by": admin["id"],
                "reason": (reason or "").strip(),
            }
        )
        .execute()
    )
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to restrict person")
    row = inserted.data[0]
    return FeedRestrictionOut(
        user_id=row["user_id"],
        restricted_by=row.get("restricted_by"),
        reason=row.get("reason") or "",
        created_at=row.get("created_at"),
    )


async def unrestrict_author(school_id: str, user_id: str) -> None:
    """Admin lifts a feed posting restriction."""
    client = get_client()
    await (
        client.table("feed_posting_restrictions")
        .delete()
        .eq("school_id", school_id)
        .eq("user_id", user_id)
        .execute()
    )


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


async def update_comment(
    school_id: str, comment_id: str, user: dict, body: FeedCommentUpdateIn
) -> FeedCommentOut:
    """Edit a comment's text. Author or admin can edit."""
    client = get_client()
    res = (
        await client.table("feed_comments")
        .select(_COMMENT_COLUMNS)
        .eq("school_id", school_id)
        .eq("id", comment_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Comment not found")
    comment = res.data[0]
    if comment["user_id"] != user["id"] and user.get("role") not in _ADMIN_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "You can't edit this comment")

    text = (body.text or "").strip()
    if not text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Comment can't be empty")

    updated = (
        await client.table("feed_comments")
        .update({"text": text})
        .eq("school_id", school_id)
        .eq("id", comment_id)
        .execute()
    )
    if not updated.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to update comment")
    return FeedCommentOut(**updated.data[0])
