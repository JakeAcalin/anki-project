from fastapi import APIRouter, HTTPException
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


@router.post("/run-now")
def run_now():
    from ..services.generator import process_daily_notes

    try:
        process_daily_notes()
    except Exception as exc:  # noqa: BLE001 - surface it, the caller wants to see failures
        raise HTTPException(502, str(exc)) from exc
    return store.get_daily_notes()
