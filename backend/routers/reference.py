from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import ReferenceNote
from ..storage import store

router = APIRouter(prefix="/api/reference", tags=["reference"])


class ReferenceNoteUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    body: Optional[str] = None
    tags: Optional[List[str]] = None
    media_ids: Optional[List[str]] = None


@router.get("")
def list_reference_notes():
    return store.list_reference_notes()


@router.post("")
def create_reference_note(note: ReferenceNote):
    store.add_reference_notes([note])
    return note


@router.get("/{note_id}")
def get_reference_note(note_id: str):
    note = store.get_reference_note(note_id)
    if not note:
        raise HTTPException(404, "Reference note not found")
    return note


@router.put("/{note_id}")
def update_reference_note(note_id: str, update: ReferenceNoteUpdate):
    note = store.get_reference_note(note_id)
    if not note:
        raise HTTPException(404, "Reference note not found")
    updated = note.model_copy(update=update.model_dump(exclude_unset=True))
    store.update_reference_note(updated)
    return updated


@router.delete("/{note_id}")
def delete_reference_note(note_id: str):
    store.delete_reference_note(note_id)
    return {"ok": True}
