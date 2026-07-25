"""Builds a .apkg from CardDraft objects using genanki.

Hierarchical tags: Anki natively treats '::' inside a tag as a nested tag tree
in the browser sidebar, so CardDraft.tags are passed straight through.
Hierarchical decks: a card's `deck` field may itself contain '::' (e.g.
'Biology::CellBiology') which genanki/Anki treats as a subdeck path.

Two note models are supported, chosen per-card via CardDraft.card_type:
Basic (Question/Answer) and Cloze (a single sentence with {{c1::...}} blanks).
"""
import hashlib
from pathlib import Path
from typing import List

import genanki

from .. import config
from ..models import CardDraft, CardType
from ..storage import store

BASIC_MODEL_NAME = "Anki Media Generator - Basic"
CLOZE_MODEL_NAME = "Anki Media Generator - Cloze"
SEQUENCE_MODEL_NAME = "Anki Media Generator - Sequence"

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
.question u { text-decoration-color: #0b5fff; text-decoration-thickness: 2px; }
hr#answer { margin: 16px 0; border: none; border-top: 1px solid #ddd; }
.answer { font-size: 20px; font-weight: 600; color: #0b5fff; margin-bottom: 12px; }
.cloze-text { font-size: 22px; font-weight: 500; }
.cloze { font-weight: 700; color: #0b5fff; }
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
.explanation mark, .cloze-text mark {
  background: #fde68a;
  color: #7c4a03;
  padding: 1px 5px;
  border-radius: 4px;
  font-weight: 600;
}
.answer-images { margin-top: 14px; }
.answer-images img { max-width: 100%; border-radius: 6px; margin-top: 8px; display: block; }

/* "Hide all, guess one": on the FRONT of a multi-blank note (a list like
   the H's and T's), Anki normally leaves the sibling blanks showing as
   plain text -- so you can read the rest of the list straight off the card
   and never actually recall it. Blank them out too, leaving only the one
   being asked. The back still shows every item, so the list stays intact
   as context once answered. Relies on Anki's .cloze-inactive wrapper
   (Anki 2.1.56+); on older versions this rule simply does nothing and
   behavior falls back to standard cloze. */
.cloze-question .cloze-inactive { font-size: 0; }
.cloze-question .cloze-inactive::before {
  content: "[...]";
  font-size: 22px;
  color: #b9b9c4;
  font-weight: 600;
}

/* Sequence cards: one card holding a whole list, revealed a step at a
   time via the button below it. */
.seq-prompt { font-size: 22px; font-weight: 600; margin-bottom: 14px; }
.seq-list { margin: 0; padding-left: 26px; font-size: 20px; line-height: 1.6; }
.seq-list li { margin: 6px 0; }
.seq-list li.seq-hidden > .seq-text { visibility: hidden; }
.seq-list li.seq-hidden::marker { color: #b9b9c4; }
.seq-list li.seq-hidden > .seq-placeholder { display: inline; }
.seq-list li > .seq-placeholder { display: none; color: #b9b9c4; font-weight: 600; }
.seq-list li.seq-revealed > .seq-text { color: #0b5fff; font-weight: 600; }
.seq-controls { margin-top: 18px; }
#seq-next {
  font: inherit; font-size: 16px; font-weight: 600;
  padding: 8px 18px; border-radius: 8px; cursor: pointer;
  border: 1px solid #0b5fff; background: #eaf1ff; color: #0b5fff;
}
#seq-next:disabled { opacity: .45; cursor: default; }
.seq-progress { font-size: 14px; color: #7a7a86; margin-left: 10px; }
"""

# Kept out of the CSS/template strings so both the .apkg export and the
# AnkiConnect push share exactly one copy of the reveal logic.
SEQUENCE_JS = """
<script>
(function () {
  var list = document.getElementById('seq-list');
  if (!list) return;
  var items = Array.prototype.slice.call(list.querySelectorAll('li'));
  var btn = document.getElementById('seq-next');
  var progress = document.getElementById('seq-progress');
  var revealAll = list.dataset.revealAll === '1';
  var next = 0;

  function paint() {
    if (progress) progress.textContent = next + ' / ' + items.length;
    if (btn) btn.disabled = next >= items.length;
  }

  if (revealAll) {
    items.forEach(function (li) {
      li.classList.remove('seq-hidden');
      li.classList.add('seq-revealed');
    });
    next = items.length;
  } else {
    items.forEach(function (li) { li.classList.add('seq-hidden'); });
  }
  paint();

  if (btn) {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (next >= items.length) return;
      items[next].classList.remove('seq-hidden');
      items[next].classList.add('seq-revealed');
      next++;
      paint();
    });
  }
})();
</script>
"""

BASIC_QFMT = '<div class="question">{{Question}}</div>'
BASIC_AFMT = (
    '<div class="question">{{Question}}</div>'
    '<hr id="answer">'
    '<div class="answer">{{Answer}}</div>'
    '{{#Explanation}}<div class="explanation">{{Explanation}}</div>{{/Explanation}}'
    '{{#Images}}<div class="answer-images">{{Images}}</div>{{/Images}}'
)

SEQUENCE_QFMT = (
    '<div class="seq-prompt">{{Prompt}}</div>'
    '<ol id="seq-list" class="seq-list" data-reveal-all="0">{{Items}}</ol>'
    '<div class="seq-controls">'
    '<button id="seq-next" type="button">Reveal next</button>'
    '<span id="seq-progress" class="seq-progress"></span>'
    "</div>" + SEQUENCE_JS
)
SEQUENCE_AFMT = (
    '<div class="seq-prompt">{{Prompt}}</div>'
    '<ol id="seq-list" class="seq-list" data-reveal-all="1">{{Items}}</ol>'
    '{{#Explanation}}<div class="explanation">{{Explanation}}</div>{{/Explanation}}'
    '{{#Images}}<div class="answer-images">{{Images}}</div>{{/Images}}' + SEQUENCE_JS
)

CLOZE_QFMT = '<div class="cloze-text cloze-question">{{cloze:Text}}</div>'
CLOZE_AFMT = (
    '<div class="cloze-text cloze-answer">{{cloze:Text}}</div>'
    '{{#Explanation}}<div class="explanation">{{Explanation}}</div>{{/Explanation}}'
    '{{#Images}}<div class="answer-images">{{Images}}</div>{{/Images}}'
)


def _stable_id(seed: str) -> int:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % (2**31 - 1) + 1


def _build_basic_model() -> genanki.Model:
    return genanki.Model(
        _stable_id(BASIC_MODEL_NAME),
        BASIC_MODEL_NAME,
        fields=[
            {"name": "Question"},
            {"name": "Answer"},
            {"name": "Explanation"},
            {"name": "Images"},
        ],
        templates=[{"name": "Card 1", "qfmt": BASIC_QFMT, "afmt": BASIC_AFMT}],
        css=CSS,
    )


def _build_sequence_model() -> genanki.Model:
    return genanki.Model(
        _stable_id(SEQUENCE_MODEL_NAME),
        SEQUENCE_MODEL_NAME,
        fields=[
            {"name": "Prompt"},
            {"name": "Items"},
            {"name": "Explanation"},
            {"name": "Images"},
        ],
        templates=[{"name": "Sequence", "qfmt": SEQUENCE_QFMT, "afmt": SEQUENCE_AFMT}],
        css=CSS,
    )


def render_sequence_items(items: List[str]) -> str:
    """One <li> per list member, each carrying a hidden-until-revealed span
    plus a visible placeholder. Built here rather than by the model so the
    escaping is guaranteed."""
    import html as _html

    out = []
    for item in items:
        text = _html.escape((item or "").strip())
        if not text:
            continue
        out.append(f'<li><span class="seq-placeholder">[ ? ]</span><span class="seq-text">{text}</span></li>')
    return "".join(out)


def _build_cloze_model() -> genanki.Model:
    return genanki.Model(
        _stable_id(CLOZE_MODEL_NAME),
        CLOZE_MODEL_NAME,
        fields=[
            {"name": "Text"},
            {"name": "Explanation"},
            {"name": "Images"},
        ],
        templates=[{"name": "Cloze", "qfmt": CLOZE_QFMT, "afmt": CLOZE_AFMT}],
        css=CSS,
        model_type=genanki.Model.CLOZE,
    )


def export_cards(cards: List[CardDraft], out_filename: str) -> Path:
    if not cards:
        raise ValueError("No cards to export.")

    basic_model = _build_basic_model()
    cloze_model = _build_cloze_model()
    sequence_model = _build_sequence_model()
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

        if card.card_type == CardType.sequence:
            note = genanki.Note(
                model=sequence_model,
                fields=[
                    card.sequence_prompt,
                    render_sequence_items(card.sequence_items),
                    card.explanation,
                    images_html,
                ],
                tags=[t.replace(" ", "_") for t in card.tags],
                guid=genanki.guid_for(card.id),
            )
        elif card.card_type == CardType.cloze:
            note = genanki.Note(
                model=cloze_model,
                fields=[card.cloze_text, card.explanation, images_html],
                tags=[t.replace(" ", "_") for t in card.tags],
                guid=genanki.guid_for(card.id),
            )
        else:
            note = genanki.Note(
                model=basic_model,
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
