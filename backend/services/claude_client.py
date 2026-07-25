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


REFERENCE_TOOL = {
    "name": "emit_reference_page",
    "description": (
        "Emit a wiki-style reference page summarizing source material that the "
        "reader wants to look up later, NOT be quizzed on."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": (
                    "A short, specific page title naming the topic -- how the reader "
                    "would search for this later. Under 8 words, no trailing period."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "One or two sentences stating what this page covers, for scanning "
                    "a list of pages at a glance."
                ),
            },
            "sections": {
                "type": "array",
                "description": (
                    "The body, broken into sections. Preserve ALL substantive detail "
                    "from the source -- this is a reference to look things up in, so "
                    "completeness matters far more than brevity. Do not drop specifics, "
                    "numbers, doses, names, caveats, or steps. Use several sections "
                    "rather than one long one."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "heading": {
                            "type": "string",
                            "description": "Short section heading. Under 6 words.",
                        },
                        "points": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": (
                                "Plain-text bullet points for this section (no HTML, no "
                                "leading bullet characters). Where a point has a natural "
                                "label, lead with it followed by a colon -- 'Definition: "
                                "...', 'Calculation: ...', 'Normal range: ...', 'Causes: "
                                "...' -- so the page can be skimmed by its labels; the "
                                "label is bolded automatically. Wrap the single most "
                                "important phrase in a point with ==double equals== to "
                                "highlight it; use at most one per point and leave a "
                                "point unmarked if nothing stands out. Start a point "
                                "with '- ' to make it a sub-point nested under the "
                                "point above it."
                            ),
                        },
                        "ordered": {
                            "type": "boolean",
                            "description": (
                                "True if this section's points are a sequence where "
                                "order matters (steps in a procedure, an algorithm), "
                                "so they render as a numbered list. False for an "
                                "unordered set of facts."
                            ),
                        },
                    },
                    "required": ["heading", "points", "ordered"],
                },
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "1-4 hierarchical tags using '::' to separate levels, e.g. "
                    "'Airway::LMA::Complications'. Broad topic first, specific last."
                ),
            },
        },
        "required": ["title", "summary", "sections", "tags"],
    },
}


def generate_reference_note(
    *,
    context_text: str,
    subject_hint: Optional[str],
    instructions: Optional[str],
) -> Dict[str, Any]:
    client = _get_client()

    prompt_parts = [
        "You are writing a personal reference page (like a wiki entry) from the "
        "source material below. This is NOT flashcard material -- the reader wants "
        "to look this up later, not be quizzed on it.",
        "",
        "Rules:",
        "- Keep ALL substantive detail from the source. Reorganize and clarify it, "
        "but do not summarize away specifics: numbers, doses, names, thresholds, "
        "exceptions, and step-by-step procedures must survive.",
        "- Structure it for fast scanning later: several short sections with clear "
        "headings, bullet points rather than paragraphs.",
        "- Use a numbered (ordered) section when the points are genuinely sequential "
        "steps; otherwise use unordered points.",
        "- If the source is a photo of a whiteboard, slide, or textbook page, "
        "transcribe its actual content faithfully rather than describing the image "
        "(don't write 'the whiteboard shows...', just record what it says).",
        "- Write in the reader's own practical register: concise, concrete, no filler.",
    ]
    if subject_hint:
        prompt_parts.append(f"- Root all tags under the subject '{subject_hint}' where sensible.")
    if instructions:
        prompt_parts.append(f"- Additional instructions from the user: {instructions}")

    prompt_parts += ["", "SOURCE MATERIAL:", context_text]

    message = client.messages.create(
        model=config.CLAUDE_TEXT_MODEL,
        max_tokens=8000,
        tools=[REFERENCE_TOOL],
        tool_choice={"type": "tool", "name": "emit_reference_page"},
        messages=[{"role": "user", "content": "\n".join(prompt_parts)}],
    )

    for block in message.content:
        if block.type == "tool_use" and block.name == "emit_reference_page":
            return block.input
    return {"title": "", "summary": "", "sections": [], "tags": []}


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

_SEQUENCE_CARD_PROPERTIES = {
    "sequence_prompt": {
        "type": "string",
        "description": (
            "A short prompt naming the list being recalled, e.g. \"The H's of "
            "reversible cardiac arrest\" or \"Steps of a rapid sequence induction\". "
            "This stays visible; it must make clear what the reader is being asked "
            "to enumerate, without giving away any member of the list."
        ),
    },
    "sequence_items": {
        "type": "array",
        "items": {"type": "string"},
        "description": (
            "The members of the list, in the order they should be recalled (the "
            "list's conventional order if it has one). Each entry is ONE member, "
            "short -- a term or short phrase, optionally with a few words of "
            "clarification after a colon, e.g. 'Hypovolemia: low blood volume'. "
            "Do not number them; the card numbers them. Do not merge two members "
            "into one entry or split one member across entries."
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


_TYPE_PROPERTIES = {
    CardType.basic: _BASIC_CARD_PROPERTIES,
    CardType.cloze: _CLOZE_CARD_PROPERTIES,
    CardType.sequence: _SEQUENCE_CARD_PROPERTIES,
}


def _build_card_tool(card_type: CardType, max_items: Optional[int] = None) -> Dict[str, Any]:
    type_properties = _TYPE_PROPERTIES.get(card_type, _BASIC_CARD_PROPERTIES)
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
    source_count: int = 0,
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

    if source_count > 1:
        prompt_parts.append(
            f"- There are {source_count} separate sources below, each marked with its own "
            "'== Source: ... ==' header. EVERY source must be represented by at least one "
            "card -- do not skip a source or fold several sources into a single card just "
            "because they seem related. Work through them one at a time and make sure none "
            "is left without a card of its own."
        )

    # Card-quality rules distilled from the widely-used medical-Anki
    # conventions (AnKing-style decks and SuperMemo's minimum information
    # principle underneath them). These matter more than they look: a card
    # that tests two things at once gets stuck at the pace of its harder
    # half, which is exactly what makes a deck feel unreviewable.
    prompt_parts += [
        "- Every card must stand alone. Someone seeing it cold, months later, with no "
        "memory of the source, should be able to tell what's being asked. Include the "
        "orienting context (the drug class, the setting, the patient population) "
        "inside the card rather than assuming it.",
        "- Avoid cards whose answer is yes/no or otherwise guessable at better than "
        "chance; ask for the specific term, number, or mechanism instead.",
        "- Prefer testing understanding (why/how/what distinguishes) over verbatim "
        "wording, except where the exact number, dose, or name IS the fact.",
    ]

    if card_type != CardType.sequence:
        # Sequence cards exist precisely to hold a whole list, so this rule
        # would contradict them.
        prompt_parts += [
            "- MINIMUM INFORMATION PRINCIPLE: each card tests exactly one fact. If a "
            "card would need 'and' to state what it's testing, split it into two cards.",
            "- Never test a bare enumeration as one unit ('name all 6 H's'). Recall of a "
            "long list in one shot is the classic unlearnable card -- break the list "
            "apart so each item is tested individually.",
        ]

    if card_type == CardType.sequence:
        prompt_parts.append(
            "- Every card here is a LIST card: one prompt naming a set or sequence, plus "
            "its members in order. Only make a card for material that genuinely is a "
            "named list worth reciting as a unit -- a mnemonic, the components of a "
            "score, the steps of a protocol, a differential. Do not force unrelated "
            "facts into list form; if the source has no real lists in it, return no "
            "cards rather than inventing them."
        )
        prompt_parts.append(
            "- Keep each member short and parallel in phrasing. Put any explanation of "
            "why the list matters in 'explanation_points', not inside the members."
        )
    elif card_type == CardType.basic:
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
            "- Use at most TWO blanks in a sentence, and only when the two are a matched "
            "pair that's meaningless apart (e.g. contrasting two drugs in one sentence). "
            "Do NOT lay a whole list out as {{c1}}, {{c2}}, {{c3}}, ... -- Anki turns each "
            "blank into its own separate card, which fragments the list. Named lists and "
            "mnemonics are handled by the separate 'List' card type instead, so here just "
            "skip them rather than trying to cram them into cloze form."
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
