from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, status

from schemas.notes import NoteIn, NoteOut, NoteUpdate
from services import notes_service
from utils.deps import require_roles

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=List[NoteOut])
async def list_notes(user: dict = Depends(require_roles("developer"))) -> List[NoteOut]:
    return await notes_service.list_notes(user["id"])


@router.post("", response_model=NoteOut, status_code=status.HTTP_201_CREATED)
async def create_note(body: NoteIn, user: dict = Depends(require_roles("developer"))) -> NoteOut:
    return await notes_service.create_note(user["id"], body)


@router.put("/{note_id}", response_model=NoteOut)
async def update_note(
    note_id: str,
    body: NoteUpdate,
    user: dict = Depends(require_roles("developer")),
) -> NoteOut:
    return await notes_service.update_note(user["id"], note_id, body)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: str, user: dict = Depends(require_roles("developer"))):
    await notes_service.delete_note(user["id"], note_id)
