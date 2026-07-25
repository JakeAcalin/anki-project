"""Near-duplicate detection for cards.

Two things create duplicates in practice:

* A Daily Notes run that overlapped another one -- both read the same
  un-carded text and asked Claude about it separately, so the same note
  comes back twice in slightly different words. That's prevented at the
  source now (the text is claimed before the model call), and this module
  is the safety net behind it.
* Re-generating from a source that's already been carded.

Because the two copies come from separate model calls they're never
byte-identical -- "high PEEP or tidal volumes" vs "PEEP 15, high tidal
volumes" -- so exact matching is useless here and we compare on similarity
instead.

Question similarity alone is not merely insufficient, it's actively
misleading: "Which nerve innervates the *anterior* tongue?" and "...the
*posterior* tongue?" score 0.94 against each other, higher than the genuine
duplicate pair this module was written for. Contrast cards are near-identical
by construction. So the question score is only ever a gate, and what actually
decides is the answer:

* **Answer containment** -- the shorter answer's content words being a subset
  of the longer's. Rewordings of one fact contain each other ("It can unseal
  the LMA" inside "High pressures can unseal the LMA"); contrast pairs don't
  (lingual vs glossopharyngeal).
* **Numeric agreement** -- two answers quoting different numbers are two
  different facts, whatever they score. This is what keeps "dose in adults"
  (1-1.5 mg/kg) apart from "dose in children" (2 mg/kg).

Even then, similarity never deletes anything by itself: `find_duplicate_groups`
only produces a list for a human to confirm.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Sequence

_TAG_RE = re.compile(r"<[^>]+>")
_NON_WORD_RE = re.compile(r"[^a-z0-9\s]+")
_WS_RE = re.compile(r"\s+")

# Words too common to say anything about whether two cards are the same;
# used only to make the candidate prefilter cheaper, never for scoring.
_STOPWORDS = frozenset(
    """a an the of in on to for with and or is are was were be been it its this that
    what which why how when where who whom does do did can could should would may might
    if then than as at by from into during vs versus""".split()
)

# Question score is only a gate -- see the module docstring. Automatic
# suppression demands a closer question than the human-reviewed list does.
_AUTO_QUESTION_THRESHOLD = 0.85
_REVIEW_QUESTION_THRESHOLD = 0.80

# How much of the shorter answer's meaning must appear in the longer one.
# This is the test that actually separates duplicates from contrast pairs,
# so it's held at the same height for both paths.
_ANSWER_CONTAINMENT_THRESHOLD = 0.70

# Skip the expensive ratio unless the token sets already overlap this much.
_PREFILTER_JACCARD = 0.5

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_SPACED_PUNCT_RE = re.compile(r"\s+([?!.,;:)\]])")


def _plain(text: str) -> str:
    """HTML card text down to comparable words."""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = text.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.lower()
    text = _NON_WORD_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def card_question_text(card: Any) -> str:
    """The 'front' of a card, whatever its type."""
    card_type = getattr(card, "card_type", None)
    type_value = getattr(card_type, "value", card_type)
    if type_value == "cloze":
        return _plain(getattr(card, "cloze_text", ""))
    if type_value == "sequence":
        return _plain(getattr(card, "sequence_prompt", ""))
    return _plain(getattr(card, "question", ""))


def card_answer_text(card: Any) -> str:
    """The 'back' of a card, whatever its type."""
    card_type = getattr(card, "card_type", None)
    type_value = getattr(card_type, "value", card_type)
    if type_value == "sequence":
        return _plain(" ".join(getattr(card, "sequence_items", []) or []))
    if type_value == "cloze":
        # A cloze's answer lives inside its text, already covered by the
        # question side; fall back to the explanation so the answer check
        # still has something to compare.
        return _plain(getattr(card, "explanation", ""))
    return _plain(getattr(card, "answer", ""))


def _readable(text: str) -> str:
    """HTML stripped for display, keeping case and punctuation.

    Distinct from `_plain`, which flattens both away so two phrasings can be
    compared -- that form is unreadable and must never reach the screen.
    """
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", '"')
        .replace("&#39;", "'")
    )
    text = _WS_RE.sub(" ", text).strip()
    # Stripping an inline tag off the end of a phrase ("an <i>LMA</i>?")
    # leaves the punctuation stranded after a space; close it back up.
    return _SPACED_PUNCT_RE.sub(r"\1", text)


def card_display_question(card: Any) -> str:
    card_type = getattr(card, "card_type", None)
    type_value = getattr(card_type, "value", card_type)
    if type_value == "cloze":
        return _readable(getattr(card, "cloze_text", ""))
    if type_value == "sequence":
        return _readable(getattr(card, "sequence_prompt", ""))
    return _readable(getattr(card, "question", ""))


def card_display_answer(card: Any) -> str:
    card_type = getattr(card, "card_type", None)
    type_value = getattr(card_type, "value", card_type)
    if type_value == "sequence":
        return _readable(", ".join(getattr(card, "sequence_items", []) or []))
    if type_value == "cloze":
        return _readable(getattr(card, "explanation", ""))
    return _readable(getattr(card, "answer", ""))


def _tokens(text: str) -> frozenset:
    return frozenset(w for w in text.split() if w not in _STOPWORDS)


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def _containment(a: frozenset, b: frozenset) -> float:
    """How much of the smaller token set is inside the larger one.

    Deliberately not Jaccard: a terse restatement of the same fact ("It can
    unseal the LMA") should still count as agreeing with the fuller one
    ("High pressures can unseal the LMA"), and containment ignores the extra
    words on the longer side that Jaccard would penalise.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def _numbers_conflict(a: str, b: str) -> bool:
    """True when both answers quote numbers and the numbers disagree.

    Two answers naming different doses, times or pressures are two different
    facts no matter how alike they read. Only fires when *both* sides carry
    numbers -- one side merely being more specific is a rewording, not a
    contradiction.
    """
    na = set(_NUMBER_RE.findall(a))
    nb = set(_NUMBER_RE.findall(b))
    return bool(na) and bool(nb) and na != nb


def _pair_scores(card_a: Any, card_b: Any) -> tuple:
    """(question similarity, answer containment) for a pair."""
    q = similarity(card_question_text(card_a), card_question_text(card_b))
    ans_a, ans_b = card_answer_text(card_a), card_answer_text(card_b)
    contain = _containment(_tokens(ans_a), _tokens(ans_b))
    return q, contain


def _looks_duplicate(card_a: Any, card_b: Any, question_threshold: float) -> bool:
    q_score, contain = _pair_scores(card_a, card_b)
    if q_score < question_threshold:
        return False
    if contain < _ANSWER_CONTAINMENT_THRESHOLD:
        return False
    return not _numbers_conflict(card_answer_text(card_a), card_answer_text(card_b))


def is_duplicate_of(card: Any, existing: Iterable[Any]) -> Any:
    """Return the first card in `existing` that `card` duplicates, else None.

    Used to stop a duplicate being stored in the first place, so it errs
    toward keeping the card: a close question is not enough on its own.
    """
    q_text = card_question_text(card)
    if not q_text:
        return None
    q_tokens = _tokens(q_text)

    for other in existing:
        other_q = card_question_text(other)
        if not other_q:
            continue
        if _jaccard(q_tokens, _tokens(other_q)) < _PREFILTER_JACCARD:
            continue
        if _looks_duplicate(card, other, _AUTO_QUESTION_THRESHOLD):
            return other
    return None


def drop_duplicates(new_cards: Sequence[Any], existing: Sequence[Any]) -> tuple:
    """Split `new_cards` into (keep, dropped) against `existing` and against
    each other, so a single batch can't introduce its own duplicates."""
    keep: List[Any] = []
    dropped: List[Any] = []
    pool = list(existing)
    for card in new_cards:
        if is_duplicate_of(card, pool) is not None:
            dropped.append(card)
            continue
        keep.append(card)
        pool.append(card)
    return keep, dropped


def find_duplicate_groups(cards: Sequence[Any]) -> List[Dict[str, Any]]:
    """Group near-identical cards for a human to review.

    Accepts a looser question match than the automatic path, since nothing
    here is removed without confirmation -- but holds the answer test at the
    same height, because a review list that flags every contrast pair in a
    deck is one nobody will trust. The oldest card in each group is listed
    first as the suggested keeper.
    """
    indexed = [(c, card_question_text(c)) for c in cards]
    indexed = [(c, q) for c, q in indexed if q]
    token_sets = [_tokens(q) for _, q in indexed]

    parent = list(range(len(indexed)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for i in range(len(indexed)):
        for j in range(i + 1, len(indexed)):
            if _jaccard(token_sets[i], token_sets[j]) < _PREFILTER_JACCARD:
                continue
            if _looks_duplicate(indexed[i][0], indexed[j][0], _REVIEW_QUESTION_THRESHOLD):
                union(i, j)

    clusters: Dict[int, List[Any]] = {}
    for idx, (card, _) in enumerate(indexed):
        clusters.setdefault(find(idx), []).append(card)

    groups = []
    for members in clusters.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda c: getattr(c, "created_at", 0.0))
        groups.append(
            {
                "keep_id": members[0].id,
                "cards": [
                    {
                        "id": c.id,
                        "card_type": getattr(getattr(c, "card_type", None), "value", "basic"),
                        "question": card_display_question(c),
                        "answer": card_display_answer(c),
                        "tags": list(getattr(c, "tags", [])),
                        "deck": getattr(c, "deck", ""),
                        "created_at": getattr(c, "created_at", 0.0),
                        "in_anki": getattr(c, "anki_note_id", None) is not None,
                    }
                    for c in members
                ],
            }
        )
    groups.sort(key=lambda g: g["cards"][0]["created_at"], reverse=True)
    return groups
