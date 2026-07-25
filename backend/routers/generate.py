from fastapi import APIRouter, HTTPException

from ..models import GenerateRequest, OutputMode
from ..services.claude_client import ClaudeNotConfigured
from ..services.generator import build_cards_from_sources, build_reference_from_sources
from ..storage import store

router = APIRouter(prefix="/api/generate", tags=["generate"])


@router.post("")
def generate(req: GenerateRequest):
    store.set_deck_name(req.deck)
    try:
        if req.output_mode == OutputMode.reference:
            note = build_reference_from_sources(
                source_ids=req.source_ids,
                deck=req.deck,
                subject_hint=req.subject_hint,
                instructions=req.instructions,
            )
            return {"output_mode": "reference", "reference_note": note, "cards": []}

        cards = build_cards_from_sources(
            source_ids=req.source_ids,
            deck=req.deck,
            card_type=req.card_type,
            subject_hint=req.subject_hint,
            instructions=req.instructions,
            max_cards=req.max_cards,
        )
    except ClaudeNotConfigured as exc:
        raise HTTPException(400, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"output_mode": "cards", "reference_note": None, "cards": cards}
