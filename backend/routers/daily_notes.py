from fastapi import APIRouter
from pydantic import BaseModel

from ..storage import store

router = APIRouter(prefix="/api/daily-notes", tags=["daily-notes"])


class DailyNotesUpdate(BaseModel):
    text: str


@router.get("")
def get_daily_notes():
    return store.get_daily_notes()


@router.put("")
def update_daily_notes(body: DailyNotesUpdate):
    return store.update_daily_notes_text(body.text)
