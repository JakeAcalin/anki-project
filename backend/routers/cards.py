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
    sequence_prompt: Optional[str] = None
    sequence_items: Optional[List[str]] = None
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


@router.post("/reorganize-topics")
def reorganize_topics():
    from ..services.claude_client import ClaudeNotConfigured
    from ..services.generator import reorganize_topics as _reorganize

    try:
        return _reorganize()
    except ClaudeNotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/duplicates")
def list_duplicates():
    """Near-identical cards, grouped for review. Read-only -- nothing is
    removed until the user says which copies to drop."""
    from ..services import dedupe

    return {"groups": dedupe.find_duplicate_groups(store.list_cards())}


class DuplicateResolve(BaseModel):
    remove_ids: List[str]


@router.post("/duplicates/resolve")
def resolve_duplicates(body: DuplicateResolve):
    """Delete the copies the user picked, here and in Anki.

    Archiving isn't enough: in this app 'archived' means 'already pushed',
    and the next Anki sync would un-archive anything Anki no longer has --
    so a duplicate left in the collection would simply come back.
    """
    from ..services import ankiconnect_client
    from ..services.ankiconnect_client import AnkiConnectError

    cards = {c.id: c for c in store.list_cards()}
    targets = [cards[cid] for cid in body.remove_ids if cid in cards]
    note_ids = [c.anki_note_id for c in targets if c.anki_note_id is not None]

    if note_ids:
        try:
            ankiconnect_client.delete_notes(note_ids)
        except AnkiConnectError as exc:
            # Keep the local copies too, so the two stay consistent and the
            # user can retry once Anki is open rather than being left with
            # cards deleted here but still coming up in reviews.
            raise HTTPException(
                400,
                f"Removed nothing: these duplicates are in Anki and couldn't be deleted there. {exc}",
            ) from exc

    for card in targets:
        store.delete_card(card.id)

    return {"removed": len(targets), "removed_from_anki": len(note_ids)}


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
