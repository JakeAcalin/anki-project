from fastapi import APIRouter
from pydantic import BaseModel

from .. import config
from ..storage import store

router = APIRouter(prefix="/api/project", tags=["project"])


class DeckNameUpdate(BaseModel):
    name: str


@router.get("")
def get_project():
    return {
        "sources": store.list_sources(),
        "media": store.list_media(),
        "cards": store.list_cards(),
        "deck_name": store.get_deck_name(),
        "claude_configured": bool(config.ANTHROPIC_API_KEY),
    }


@router.put("/deck-name")
def set_deck_name(body: DeckNameUpdate):
    store.set_deck_name(body.name)
    return {"deck_name": store.get_deck_name()}


@router.post("/reset")
def reset_project():
    store.reset()
    return {"ok": True}
