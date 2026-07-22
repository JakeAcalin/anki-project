import re
import time

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from ..models import ExportRequest
from ..services.anki_export import export_cards
from ..storage import store

router = APIRouter(prefix="/api/export", tags=["export"])


def _safe_filename(name: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_") or "deck"
    return name


@router.post("")
def export(req: ExportRequest):
    all_cards = store.list_cards()
    if req.card_ids:
        wanted = set(req.card_ids)
        cards = [c for c in all_cards if c.id in wanted]
    else:
        cards = [c for c in all_cards if c.included]

    if req.deck_name:
        for c in cards:
            c.deck = req.deck_name

    if not cards:
        raise HTTPException(400, "No cards selected for export.")

    filename = req.filename or f"{_safe_filename(store.get_deck_name())}_{int(time.time())}.apkg"
    if not filename.endswith(".apkg"):
        filename += ".apkg"

    try:
        out_path = export_cards(cards, filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    return FileResponse(
        out_path,
        media_type="application/octet-stream",
        filename=filename,
    )
