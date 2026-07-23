"""Thin wrapper around the Anthropic API: image captioning (vision) and
structured flashcard generation (tool-use for guaranteed JSON output)."""
import base64
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

from .. import config
from ..models import CardType

_client = None


class ClaudeNotConfigured(RuntimeError):
    pass


def _get_client():
    global _client
    if _client is None:
        if not config.ANTHROPIC_API_KEY:
            raise ClaudeNotConfigured(
                "ANTHROPIC_API_KEY is not set. Add it to your .env file to enable "
                "AI-generated captions and flashcards."
            )
        import anthropic

        _client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    return _client


def _image_block(path: Path) -> Dict[str, Any]:
    mime_type = mimetypes.guess_type(str(path))[0] or "image/jpeg"
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": mime_type, "data": data},
    }


CAPTION_TOOL = {
    "name": "describe_image",
    "description": "Describe an image for someone building study flashcards from it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "description": {
                "type": "string",
                "description": (
                    "2-5 sentences describing the image: diagrams, labels, text, charts, "
                    "or key objects and how they relate to each other."
                ),
            },
            "highlighted_excerpts": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Verbatim text that a STUDENT has marked with a highlighter pen or "
                    "similar hand-marking (e.g. yellow/pink/green marker strokes over "
                    "printed text). Do NOT include text that is merely bold, italic, in a "
                    "caption, or otherwise emphasized by the textbook's own typesetting — "
                    "only text a reader visibly highlighted themselves after printing. "
                    "Empty array if there's no such hand-highlighting in the image."
                ),
            },
        },
        "required": ["description", "highlighted_excerpts"],
    },
}


def caption_image(path: Path) -> Dict[str, Any]:
    client = _get_client()
    message = client.messages.create(
        model=config.CLAUDE_VISION_MODEL,
        max_tokens=600,
        tools=[CAPTION_TOOL],
        tool_choice={"type": "tool", "name": "describe_image"},
        messages=[
            {
                "role": "user",
                "content": [
                    _image_block(path),
                    {
                        "type": "text",
                        "text": "Analyze this image for flashcard-building purposes.",
                    },
                ],
            }
        ],
    )
    for block in message.content:
        if block.type == "tool_use" and block.name == "describe_image":
            return {
                "description": block.input.get("description", "").strip(),
                "highlighted_excerpts": [
                    h.strip() for h in block.input.get("highlighted_excerpts", []) if h.strip()
                ],
            }
    return {"description": "", "highlighted_excerpts": []}


_BASIC_CARD_PROPERTIES = {
    "question": {
        "type": "string",
        "description": (
            "The front of the card: one short, focused question, ideally under 15 "
            "words. No preamble, no multi-part questions. Mark up the single most "
            "important term or qualifier using plain-text emphasis markers -- "
            "**double asterisks** for bold on the key concept being tested, and "
            "*single asterisks* or __double underscores__ sparingly for a critical "
            "qualifier (e.g. a negation, timeframe, or comparison word) if there is "
            "one. Usually just one emphasized span is enough; don't over-mark. "
            "Example: 'Which nerve is **most** at risk in the *lithotomy* position?'"
        ),
    },
    "answer": {
        "type": "string",
        "description": (
            "The shortest phrase that correctly answers the question — a term, a "
            "number, a short clause. Ideally under 10 words. Do not restate the "
            "question or repeat the explanation here."
        ),
    },
}

_CLOZE_CARD_PROPERTIES = {
    "cloze_text": {
        "type": "string",
        "description": (
            "One short, self-contained sentence with the key term(s) to test wrapped in "
            "Anki cloze syntax, ALWAYS including a hint: {{c1::hidden text::hint}}. Keep "
            "each individual deletion SHORT -- one or two words (a term, a number, a "
            "name), never a long phrase or clause. If the key fact is naturally a longer "
            "phrase, pick the single most essential word inside it to blank out instead "
            "of hiding the whole thing. The hint should orient the reader (a category, "
            "type, or short label) without giving away the answer itself -- never omit "
            "it, since a bare blank with no hint often leaves the card unanswerable out "
            "of context. Example: 'Atropine is a {{c1::tertiary amine::amine type}}, "
            "while glycopyrrolate is a {{c2::quaternary amine::amine type}}.' If the "
            "sentence describes a list of parallel items (several strategies, causes, "
            "exceptions, etc.), give each item its own numbered blank ({{c1::...}}, "
            "{{c2::...}}, {{c3::...}}, ...) so every item in the list gets tested, "
            "rather than leaving some untested or cramming them into one long deletion. "
            "Keep the sentence itself short and unambiguous."
        ),
    },
}

_SHARED_CARD_PROPERTIES = {
    "explanation_points": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "2-4 short, plain-text bullet points (no HTML, no bullet characters -- "
            "just the sentence) that give the answer-side depth: mechanism, context, "
            "a common misconception, or an example. Each point should be one short, "
            "easily digestible sentence, not a paragraph. Wrap the single most "
            "important phrase in each point with ==double equals signs== so it gets "
            "highlighted -- usually the specific fact, number, or distinguishing "
            "detail someone reviewing this card would want to catch at a glance. "
            "Mark at most one span per point; leave a point unmarked if nothing in "
            "it truly stands out."
        ),
    },
    "tags": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "1-4 hierarchical tags using '::' to separate levels, e.g. "
            "'Biology::CellBiology::Mitochondria'. Broad topic first, specific "
            "concept last."
        ),
    },
}


def _build_card_tool(card_type: CardType, max_items: Optional[int] = None) -> Dict[str, Any]:
    type_properties = _BASIC_CARD_PROPERTIES if card_type == CardType.basic else _CLOZE_CARD_PROPERTIES
    properties = {**type_properties, **_SHARED_CARD_PROPERTIES}
    cards_schema: Dict[str, Any] = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": list(properties.keys()),
        },
    }
    if max_items is not None:
        cards_schema["maxItems"] = max_items
    return {
        "name": "emit_cards",
        "description": "Emit a set of Anki study flashcards derived from the given source material.",
        "input_schema": {
            "type": "object",
            "properties": {"cards": cards_schema},
            "required": ["cards"],
        },
    }


def generate_cards(
    *,
    context_text: str,
    card_type: CardType,
    subject_hint: Optional[str],
    instructions: Optional[str],
    max_cards: int,
    auto_count: bool,
    auto_count_cap: Optional[int] = None,
    has_truelearn_notes: bool = False,
) -> List[Dict[str, Any]]:
    client = _get_client()

    prompt_parts = [
        "You are building a hierarchically-tagged Anki deck from study material.",
        "Read the SOURCE MATERIAL below and produce high-quality flashcards.",
        "Some of it may describe figures, graphs, or photos from the original source "
        "(e.g. 'Fig. 4.19 shows...') — use that description as content, but the cards "
        "themselves are text-only, so make sure each card stands on its own without "
        "requiring the reader to see the original image.",
        "",
        "Rules:",
    ]

    if auto_count:
        prompt_parts.append(
            "- Some source material below is marked 'HIGHLIGHTED BY STUDENT' — this is text "
            "the learner specifically flagged as important. Produce exactly one focused card "
            "per distinct highlighted concept; don't skip any, and don't invent extra cards "
            "for non-highlighted content unless it's needed to make a highlighted card make "
            "sense on its own. The number of cards should come from the number of distinct "
            "highlighted concepts, not a fixed target."
        )
        if has_truelearn_notes:
            prompt_parts.append(
                "- Source material blocks that start with '[Topic: ...]' are notes the "
                "student already wrote themselves after missing a question on TrueLearn — "
                "each such block is one distinct concept. Produce exactly one focused card "
                "per '[Topic: ...]' block, in addition to any highlighted-concept cards "
                "above. Use the topic to inform the card's hierarchical tag, but clean it "
                "up rather than copying it verbatim (drop trailing letters/version markers "
                "like '(A)' and redundant repetition)."
            )
    else:
        prompt_parts.append(
            f"- Produce at most {max_cards} cards, prioritizing the most important, testable "
            "concepts."
        )

    if card_type == CardType.basic:
        prompt_parts.append(
            "- Each card must be atomic: one short question, one short answer. Favor many "
            "small cards over a few big ones — if a topic has several distinct facts, split "
            "it into separate cards rather than cramming them into one question/answer."
        )
        prompt_parts.append(
            "- Keep 'question' and 'answer' short and easy to scan at a glance. Put depth "
            "and nuance in 'explanation_points' instead, never in the question or answer "
            "themselves."
        )
    else:
        prompt_parts.append(
            "- Each card is a single cloze sentence ('cloze_text') that tests one atomic "
            "fact. Favor many small cards over cramming multiple unrelated facts into one "
            "sentence."
        )

    prompt_parts.append(
        "- Assign hierarchical tags with '::' (e.g. Topic::Subtopic::Detail). Reuse the same "
        "top-level tag across related cards so the deck organizes into a clean tree."
    )
    if subject_hint:
        prompt_parts.append(f"- Root all tags under the subject '{subject_hint}' where sensible.")
    if instructions:
        prompt_parts.append(f"- Additional instructions from the user: {instructions}")

    prompt_parts += [
        "",
        "SOURCE MATERIAL:",
        context_text,
    ]

    # "auto_count" tells Claude to size the output itself (one card per
    # highlighted concept / TrueLearn row) instead of a fixed target -- but
    # the caller usually still knows a real upper bound (the number of
    # concepts/rows involved), so enforce it as a hard cap the same way
    # max_cards is enforced below: the prompt is a request, not a guarantee.
    max_items = auto_count_cap if auto_count else max_cards
    tool = _build_card_tool(card_type, max_items=max_items)
    message = client.messages.create(
        model=config.CLAUDE_TEXT_MODEL,
        max_tokens=8000,
        tools=[tool],
        tool_choice={"type": "tool", "name": "emit_cards"},
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "emit_cards":
            cards = block.input.get("cards", [])
            # The prompt (and the schema's maxItems above) only *ask* Claude
            # to stay within bounds -- models don't always comply exactly,
            # so enforce it here too.
            if max_items is not None:
                cards = cards[:max_items]
            return cards
    return []
