"""Builds a .apkg from CardDraft objects using genanki.

Hierarchical tags: Anki natively treats '::' inside a tag as a nested tag tree
in the browser sidebar, so CardDraft.tags are passed straight through.
Hierarchical decks: a card's `deck` field may itself contain '::' (e.g.
'Biology::CellBiology') which genanki/Anki treats as a subdeck path.
"""
import hashlib
from pathlib import Path
from typing import List

import genanki

from .. import config
from ..models import CardDraft
from ..storage import store

MODEL_NAME = "Anki Media Generator - Explained"

CSS = """
.card {
  font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
  font-size: 20px;
  text-align: left;
  color: #1a1a1a;
  background-color: #fafafa;
  padding: 20px;
  line-height: 1.4;
}
.question { font-size: 22px; font-weight: 600; }
hr#answer { margin: 16px 0; border: none; border-top: 1px solid #ddd; }
.answer { font-size: 20px; font-weight: 600; color: #0b5fff; margin-bottom: 12px; }
.explanation {
  font-size: 16px;
  line-height: 1.55;
  color: #2a2a2a;
  background: #ffffff;
  border-left: 4px solid #0b5fff;
  padding: 10px 14px;
  border-radius: 4px;
  margin-top: 8px;
}
.explanation p { margin: 0 0 8px 0; }
.explanation ul { margin: 4px 0 8px 20px; }
.answer-images { margin-top: 14px; }
.answer-images img { max-width: 100%; border-radius: 6px; margin-top: 8px; display: block; }
"""

QFMT = '<div class="question">{{Question}}</div>'
AFMT = (
    '<div class="question">{{Question}}</div>'
    '<hr id="answer">'
    '<div class="answer">{{Answer}}</div>'
    '{{#Explanation}}<div class="explanation">{{Explanation}}</div>{{/Explanation}}'
    '{{#Images}}<div class="answer-images">{{Images}}</div>{{/Images}}'
)


def _stable_id(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) + 1


def _build_model() -> genanki.Model:
    return genanki.Model(
        _stable_id(MODEL_NAME),
        MODEL_NAME,
        fields=[
            {"name": "Question"},
            {"name": "Answer"},
            {"name": "Explanation"},
            {"name": "Images"},
        ],
        templates=[{"name": "Card 1", "qfmt": QFMT, "afmt": AFMT}],
        css=CSS,
    )


def export_cards(cards: List[CardDraft], out_filename: str) -> Path:
    if not cards:
        raise ValueError("No cards to export.")

    model = _build_model()
    decks_by_name = {}
    media_paths_by_filename = {}  # dedupe: a shared image must appear once in the package

    for card in cards:
        deck_name = card.deck or "Default"
        if deck_name not in decks_by_name:
            decks_by_name[deck_name] = genanki.Deck(_stable_id(deck_name), deck_name)

        images_html = ""
        for media_id in card.media_ids:
            media = store.get_media(media_id)
            if not media:
                continue
            media_path = config.MEDIA_DIR / media.filename
            if not media_path.exists():
                continue
            media_paths_by_filename[media.filename] = str(media_path)
            images_html += f'<img src="{media.filename}">'

        note = genanki.Note(
            model=model,
            fields=[card.question, card.answer, card.explanation, images_html],
            tags=[t.replace(" ", "_") for t in card.tags],
            guid=genanki.guid_for(card.id),
        )
        decks_by_name[deck_name].add_note(note)

    package = genanki.Package(list(decks_by_name.values()))
    package.media_files = list(media_paths_by_filename.values())

    out_path = config.EXPORT_DIR / out_filename
    package.write_to_file(str(out_path))
    return out_path
