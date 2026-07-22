from fastapi import APIRouter, HTTPException

from ..models import GenerateRequest
from ..services.claude_client import ClaudeNotConfigured
from ..services.generator import build_cards_from_sources
from ..storage import store

router = APIRouter(prefix="/api/generate", tags=["generate"])


@router.post("")
def generate(req: GenerateRequest):
    store.set_deck_name(req.deck)
    try:
        cards = build_cards_from_sources(
            source_ids=req.source_ids,
            deck=req.deck,
            subject_hint=req.subject_hint,
            instructions=req.instructions,
            max_cards=req.max_cards,
        )
    except ClaudeNotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return cards
