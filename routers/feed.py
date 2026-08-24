"""School Feed — posts (photo(s) + caption), likes and comments for all users."""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from schemas.feed import (
    FeedCommentCreateIn,
    FeedCommentOut,
    FeedCommentUpdateIn,
    FeedLikeOut,
    FeedPostCreateIn,
    FeedPostOut,
    FeedPostUpdateIn,
    FeedRestrictionIn,
    FeedRestrictionOut,
)
from services import feed_service
from services.feed_media_service import resolve_feed_file
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/feed", tags=["feed"])

_admin_dep = require_roles("school_admin", "principal", "vice_principal", "super_admin")


@router.post("/upload-media")
async def upload_media(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
) -> dict:
    return await feed_service.upload_media(user["school_id"], file)


@router.get("", response_model=List[FeedPostOut])
async def list_posts(
    limit: int = Query(default=20, ge=1, le=100),
    before_id: Optional[str] = Query(default=None),
    user: dict = Depends(current_user),
) -> List[FeedPostOut]:
    return await feed_service.list_posts(user["school_id"], user["id"], limit, before_id)


@router.post("", response_model=FeedPostOut, status_code=status.HTTP_201_CREATED)
async def create_post(
    body: FeedPostCreateIn,
    user: dict = Depends(current_user),
) -> FeedPostOut:
    return await feed_service.create_post(user["school_id"], user, body)


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post(
    post_id: str,
    user: dict = Depends(current_user),
) -> Response:
    await feed_service.delete_post(user["school_id"], post_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{post_id}", response_model=FeedPostOut)
async def update_post(
    post_id: str,
    body: FeedPostUpdateIn,
    user: dict = Depends(current_user),
) -> FeedPostOut:
    return await feed_service.update_post(user["school_id"], post_id, user, body)


@router.post("/restrictions/{user_id}", response_model=FeedRestrictionOut)
async def restrict_author(
    user_id: str,
    body: FeedRestrictionIn,
    user: dict = Depends(_admin_dep),
) -> FeedRestrictionOut:
    return await feed_service.restrict_author(user["school_id"], user_id, user, body.reason)


@router.delete("/restrictions/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unrestrict_author(
    user_id: str,
    user: dict = Depends(_admin_dep),
) -> Response:
    await feed_service.unrestrict_author(user["school_id"], user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{post_id}/like", response_model=FeedLikeOut)
async def toggle_like(
    post_id: str,
    user: dict = Depends(current_user),
) -> FeedLikeOut:
    return await feed_service.toggle_like(user["school_id"], post_id, user["id"])


@router.get("/{post_id}/comments", response_model=List[FeedCommentOut])
async def list_comments(
    post_id: str,
    user: dict = Depends(current_user),
) -> List[FeedCommentOut]:
    return await feed_service.list_comments(user["school_id"], post_id)


@router.post(
    "/{post_id}/comments",
    response_model=FeedCommentOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_comment(
    post_id: str,
    body: FeedCommentCreateIn,
    user: dict = Depends(current_user),
) -> FeedCommentOut:
    return await feed_service.add_comment(user["school_id"], post_id, user, body.text)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_comment(
    comment_id: str,
    user: dict = Depends(current_user),
) -> Response:
    await feed_service.delete_comment(user["school_id"], comment_id, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/comments/{comment_id}", response_model=FeedCommentOut)
async def update_comment(
    comment_id: str,
    body: FeedCommentUpdateIn,
    user: dict = Depends(current_user),
) -> FeedCommentOut:
    return await feed_service.update_comment(user["school_id"], comment_id, user, body)


@router.get("/files/{filename}")
async def get_feed_file(
    filename: str,
    user: dict = Depends(current_user),
) -> FileResponse:
    path, mime = resolve_feed_file(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)
