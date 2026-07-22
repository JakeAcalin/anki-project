from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..services import ankiconnect_client
from ..storage import store

router = APIRouter(prefix="/api/anki-connect", tags=["anki-connect"])


class PushRequest(BaseModel):
    card_ids: Optional[List[str]] = None
    sync_after: bool = True


@router.get("/status")
def status():
    return {"available": ankiconnect_client.is_available()}


@router.post("/push")
def push(req: PushRequest):
    all_cards = store.list_cards()
    if req.card_ids:
        wanted = set(req.card_ids)
        cards = [c for c in all_cards if c.id in wanted]
    else:
        cards = [c for c in all_cards if c.included]

    if not cards:
        raise HTTPException(400, "No cards selected to push.")

    try:
        result = ankiconnect_client.push_cards(cards)
    except ankiconnect_client.AnkiConnectError as exc:
        raise HTTPException(502, str(exc)) from exc

    if req.sync_after:
        try:
            ankiconnect_client.trigger_sync()
            result["synced"] = True
        except ankiconnect_client.AnkiConnectError as exc:
            result["synced"] = False
            result["sync_error"] = str(exc)

    return result
