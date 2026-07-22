from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..models import CardDraft, CardType
from ..storage import store

router = APIRouter(prefix="/api/cards", tags=["cards"])


class CardUpdate(BaseModel):
    card_type: Optional[CardType] = None
    question: Optional[str] = None
    answer: Optional[str] = None
    cloze_text: Optional[str] = None
    explanation: Optional[str] = None
    tags: Optional[List[str]] = None
    media_ids: Optional[List[str]] = None
    deck: Optional[str] = None
    included: Optional[bool] = None
    archived: Optional[bool] = None


@router.get("")
def list_cards():
    return store.list_cards()


@router.get("/tags")
def list_tags():
    return store.all_tags()


@router.post("")
def create_card(card: CardDraft):
    store.add_cards([card])
    return card


@router.put("/{card_id}")
def update_card(card_id: str, update: CardUpdate):
    card = store.get_card(card_id)
    if not card:
        raise HTTPException(404, "Card not found")
    data = update.model_dump(exclude_unset=True)
    updated = card.model_copy(update=data)
    store.update_card(updated)
    return updated


@router.delete("/{card_id}")
def delete_card(card_id: str):
    store.delete_card(card_id)
    return {"ok": True}
