from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.notes import NoteIn, NoteOut, NoteUpdate

COLUMNS = "id,title,body,color,is_pinned,created_at,updated_at"


def _row_to_out(row: dict) -> NoteOut:
    return NoteOut(
        id=str(row["id"]),
        title=row.get("title") or "",
        body=row.get("body") or "",
        color=row.get("color") or "default",
        is_pinned=bool(row.get("is_pinned", False)),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def list_notes(user_id: str) -> list[NoteOut]:
    client = get_client()
    res = (
        await client.table("developer_notes")
        .select(COLUMNS)
        .eq("user_id", user_id)
        .order("is_pinned", desc=True)
        .order("updated_at", desc=True)
        .execute()
    )
    return [_row_to_out(r) for r in res.data]


async def create_note(user_id: str, body: NoteIn) -> NoteOut:
    client = get_client()
    res = (
        await client.table("developer_notes")
        .insert({
            "user_id": user_id,
            "title": body.title.strip(),
            "body": body.body,
            "color": body.color,
            "is_pinned": body.is_pinned,
        })
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not create note")
    return _row_to_out(res.data[0])


async def update_note(user_id: str, note_id: str, body: NoteUpdate) -> NoteOut:
    client = get_client()
    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if body.title is not None:
        updates["title"] = body.title.strip()
    if body.body is not None:
        updates["body"] = body.body
    if body.color is not None:
        updates["color"] = body.color
    if body.is_pinned is not None:
        updates["is_pinned"] = body.is_pinned

    res = (
        await client.table("developer_notes")
        .update(updates)
        .eq("id", note_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
    return _row_to_out(res.data[0])


async def delete_note(user_id: str, note_id: str) -> None:
    client = get_client()
    res = (
        await client.table("developer_notes")
        .delete()
        .eq("id", note_id)
        .eq("user_id", user_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Note not found")
