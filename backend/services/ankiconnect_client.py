"""Client for AnkiConnect (https://foosoft.net/projects/anki-connect/), a
local Anki desktop add-on that exposes an HTTP API on the same machine. This
is only reachable when this backend runs on the same computer as Anki
desktop, with the add-on installed and Anki open -- there is no way to reach
a user's AnkiWeb account directly, since AnkiWeb has no public API.

Idempotency: rather than stamping a visible field onto every note (which
cluttered Anki's editor), each CardDraft's own `anki_note_id` records which
Anki note it became after a successful push. Re-pushing a card updates that
same note directly; only cards pushed for the first time call addNote.
"""
import base64
from typing import Any, Dict, List

import requests

from .. import config


class AnkiConnectError(RuntimeError):
    pass


BASIC_SYNC_MODEL = "Anki Media Generator - Basic (Synced)"
CLOZE_SYNC_MODEL = "Anki Media Generator - Cloze (Synced)"

# Older pushes stamped a hidden field onto notes for matching purposes.
# That's no longer needed (see module docstring) and cluttered Anki's note
# editor, so _ensure_models() strips it from any model that still has it.
_LEGACY_FIELD = "CardId"


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


def _strip_legacy_field_if_present(model_name: str) -> None:
    try:
        fields = _invoke("modelFieldNames", modelName=model_name) or []
    except AnkiConnectError:
        return
    if _LEGACY_FIELD in fields:
        try:
            _invoke("modelFieldRemove", modelName=model_name, fieldName=_LEGACY_FIELD)
        except AnkiConnectError:
            pass  # not fatal -- worst case the old field lingers, harmless


def _ensure_models() -> None:
    from . import anki_export  # reuse the exact same templates/css as .apkg export

    if not _model_exists(BASIC_SYNC_MODEL):
        _invoke(
            "createModel",
            modelName=BASIC_SYNC_MODEL,
            inOrderFields=["Question", "Answer", "Explanation", "Images"],
            css=anki_export.CSS,
            isCloze=False,
            cardTemplates=[
                {"Name": "Card 1", "Front": anki_export.BASIC_QFMT, "Back": anki_export.BASIC_AFMT}
            ],
        )
    else:
        _strip_legacy_field_if_present(BASIC_SYNC_MODEL)

    if not _model_exists(CLOZE_SYNC_MODEL):
        _invoke(
            "createModel",
            modelName=CLOZE_SYNC_MODEL,
            inOrderFields=["Text", "Explanation", "Images"],
            css=anki_export.CSS,
            isCloze=True,
            cardTemplates=[
                {"Name": "Cloze", "Front": anki_export.CLOZE_QFMT, "Back": anki_export.CLOZE_AFMT}
            ],
        )
    else:
        _strip_legacy_field_if_present(CLOZE_SYNC_MODEL)


def _upload_media(filename: str, path) -> None:
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    _invoke("storeMediaFile", filename=filename, data=data)


def push_cards(cards: List[Any]) -> Dict[str, Any]:
    """Push CardDraft objects into the local Anki collection: add new ones,
    update ones that were pushed before (matched by the stored
    anki_note_id), and skip anything that outright fails so one bad card
    doesn't block the rest."""
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
                }
            else:
                model_name = BASIC_SYNC_MODEL
                fields = {
                    "Question": card.question,
                    "Answer": card.answer,
                    "Explanation": card.explanation,
                    "Images": images_html,
                }

            tags = [t.replace(" ", "_") for t in card.tags]

            note_id = card.anki_note_id
            note_updated = False
            if note_id is not None:
                try:
                    _invoke("updateNoteFields", note={"id": note_id, "fields": fields})
                    try:
                        _invoke("updateNoteTags", note=note_id, tags=" ".join(tags))
                    except AnkiConnectError:
                        pass  # older AnkiConnect versions may not have this action
                    try:
                        # Deck membership is a property of a note's cards, not
                        # the note itself, so moving decks means updating
                        # every card under this note (findCards) even though
                        # everything else here is addressed by note ID.
                        note_card_ids = _invoke("findCards", query=f"nid:{note_id}") or []
                        if note_card_ids:
                            _invoke("changeDeck", cards=note_card_ids, deck=deck_name)
                    except AnkiConnectError:
                        pass  # deck move is best-effort; the field/tag update above still counts as success
                    note_updated = True
                    updated.append(card.id)
                except AnkiConnectError:
                    # The note this card used to point to is gone (e.g. deleted
                    # in Anki) -- fall through and add it fresh instead.
                    note_id = None

            if note_id is None and not note_updated:
                new_note_id = _invoke(
                    "addNote",
                    note={
                        "deckName": deck_name,
                        "modelName": model_name,
                        "fields": fields,
                        "tags": tags,
                        "options": {"allowDuplicate": True},
                    },
                )
                card.anki_note_id = new_note_id
                store.update_card(card)
                added.append(card.id)

        except AnkiConnectError as exc:
            failed.append({"card_id": card.id, "error": str(exc)})

    return {"added": added, "updated": updated, "failed": failed}


def trigger_sync() -> None:
    _invoke("sync")


def find_deleted_note_ids(note_ids: List[int]) -> List[int]:
    """Given note IDs this app previously pushed, return the ones that no
    longer exist in Anki (e.g. deleted there directly, outside this app --
    AnkiConnect's notesInfo returns an empty dict for any ID that's gone)."""
    if not note_ids:
        return []
    infos = _invoke("notesInfo", notes=note_ids) or []
    deleted = []
    for note_id, info in zip(note_ids, infos):
        if not info:
            deleted.append(note_id)
    return deleted


def sync_check() -> Dict[str, Any]:
    """Reconcile every archived ("already pushed") card against Anki's
    actual state: any card whose note has been deleted in Anki (outside
    this app) is un-archived so it flows back into the normal review/push
    list -- the user asked to have the option to remake or permanently
    delete it, rather than have it silently stay "already pushed" when it
    isn't.

    Cards archived without a stored Anki note ID (pushed before this app
    tracked one, or archived some other way) have nothing to check against
    -- treat "can't confirm it's in Anki" the same as "it's not," for the
    same reason."""
    from ..storage import store

    archived_cards = [c for c in store.list_cards() if c.archived]
    trackable = [c for c in archived_cards if c.anki_note_id is not None]
    untrackable = [c for c in archived_cards if c.anki_note_id is None]

    deleted_ids = set(find_deleted_note_ids([c.anki_note_id for c in trackable]))

    reset_card_ids = []
    for card in trackable:
        if card.anki_note_id in deleted_ids:
            card.archived = False
            card.included = True
            card.anki_note_id = None
            store.update_card(card)
            reset_card_ids.append(card.id)

    for card in untrackable:
        card.archived = False
        card.included = True
        store.update_card(card)
        reset_card_ids.append(card.id)

    return {
        "checked": len(archived_cards),
        "still_in_anki": len(archived_cards) - len(reset_card_ids),
        "reset_card_ids": reset_card_ids,
    }
