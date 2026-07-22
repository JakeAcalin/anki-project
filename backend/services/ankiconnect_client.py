"""Client for AnkiConnect (https://foosoft.net/projects/anki-connect/), a
local Anki desktop add-on that exposes an HTTP API on the same machine. This
is only reachable when this backend runs on the same computer as Anki
desktop, with the add-on installed and Anki open -- there is no way to reach
a user's AnkiWeb account directly, since AnkiWeb has no public API.

Idempotency: AnkiConnect's addNote doesn't accept a caller-supplied id, so we
stamp every note with a hidden "CardId" field (not referenced by any card
template, so it never shows on the card face) holding our internal
CardDraft.id. Re-pushing a card looks up that id via findNotes and updates
the existing note instead of creating a duplicate.
"""
import base64
from typing import Any, Dict, List, Optional

import requests

from .. import config


class AnkiConnectError(RuntimeError):
    pass


BASIC_SYNC_MODEL = "Anki Media Generator - Basic (Synced)"
CLOZE_SYNC_MODEL = "Anki Media Generator - Cloze (Synced)"


def _invoke(action: str, **params: Any) -> Any:
    payload: Dict[str, Any] = {"action": action, "version": 6, "params": params}
    if config.ANKICONNECT_API_KEY:
        payload["key"] = config.ANKICONNECT_API_KEY
    try:
        resp = requests.post(config.ANKICONNECT_URL, json=payload, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise AnkiConnectError(
            f"Couldn't reach AnkiConnect at {config.ANKICONNECT_URL}. Make sure Anki "
            "desktop is open (on this same machine) with the AnkiConnect add-on installed."
        ) from exc
    if data.get("error"):
        raise AnkiConnectError(str(data["error"]))
    return data.get("result")


def is_available() -> bool:
    try:
        _invoke("version")
        return True
    except AnkiConnectError:
        return False


def _model_exists(name: str) -> bool:
    return name in (_invoke("modelNames") or [])


def _ensure_models() -> None:
    from . import anki_export  # reuse the exact same templates/css as .apkg export

    if not _model_exists(BASIC_SYNC_MODEL):
        _invoke(
            "createModel",
            modelName=BASIC_SYNC_MODEL,
            inOrderFields=["Question", "Answer", "Explanation", "Images", "CardId"],
            css=anki_export.CSS,
            isCloze=False,
            cardTemplates=[
                {"Name": "Card 1", "Front": anki_export.BASIC_QFMT, "Back": anki_export.BASIC_AFMT}
            ],
        )
    if not _model_exists(CLOZE_SYNC_MODEL):
        _invoke(
            "createModel",
            modelName=CLOZE_SYNC_MODEL,
            inOrderFields=["Text", "Explanation", "Images", "CardId"],
            css=anki_export.CSS,
            isCloze=True,
            cardTemplates=[
                {"Name": "Cloze", "Front": anki_export.CLOZE_QFMT, "Back": anki_export.CLOZE_AFMT}
            ],
        )


def _find_note_id(card_id: str) -> Optional[int]:
    ids = _invoke("findNotes", query=f'"CardId:{card_id}"')
    return ids[0] if ids else None


def _upload_media(filename: str, path) -> None:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    _invoke("storeMediaFile", filename=filename, data=data)


def push_cards(cards: List[Any]) -> Dict[str, Any]:
    """Push CardDraft objects into the local Anki collection: add new ones,
    update ones that were pushed before (matched by CardId), and skip
    anything that outright fails so one bad card doesn't block the rest."""
    from ..models import CardType
    from ..storage import store

    _ensure_models()

    added, updated, failed = [], [], []
    known_decks = set()

    for card in cards:
        try:
            deck_name = card.deck or "Default"
            if deck_name not in known_decks:
                _invoke("createDeck", deck=deck_name)
                known_decks.add(deck_name)

            images_html = ""
            for media_id in card.media_ids:
                media = store.get_media(media_id)
                if not media:
                    continue
                media_path = config.MEDIA_DIR / media.filename
                if not media_path.exists():
                    continue
                _upload_media(media.filename, media_path)
                images_html += f'<img src="{media.filename}">'

            if card.card_type == CardType.cloze:
                model_name = CLOZE_SYNC_MODEL
                fields = {
                    "Text": card.cloze_text,
                    "Explanation": card.explanation,
                    "Images": images_html,
                    "CardId": card.id,
                }
            else:
                model_name = BASIC_SYNC_MODEL
                fields = {
                    "Question": card.question,
                    "Answer": card.answer,
                    "Explanation": card.explanation,
                    "Images": images_html,
                    "CardId": card.id,
                }

            tags = [t.replace(" ", "_") for t in card.tags]
            existing_note_id = _find_note_id(card.id)

            if existing_note_id:
                _invoke("updateNoteFields", note={"id": existing_note_id, "fields": fields})
                try:
                    _invoke("updateNoteTags", note=existing_note_id, tags=" ".join(tags))
                except AnkiConnectError:
                    pass  # older AnkiConnect versions may not have this action
                updated.append(card.id)
            else:
                _invoke(
                    "addNote",
                    note={
                        "deckName": deck_name,
                        "modelName": model_name,
                        "fields": fields,
                        "tags": tags,
                        "options": {"allowDuplicate": True},
                    },
                )
                added.append(card.id)

        except AnkiConnectError as exc:
            failed.append({"card_id": card.id, "error": str(exc)})

    return {"added": added, "updated": updated, "failed": failed}


def trigger_sync() -> None:
    _invoke("sync")
